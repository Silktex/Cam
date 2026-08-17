"""
Characterization tests for the Processing Router.

Pins EVERY /api/processing endpoint's current response shapes (status code +
JSON body) at the service boundary, so that extraction of orchestration from
api/app/routers/processing.py into app/services modules is behavior-identical.

These tests MUST pass UNCHANGED before and after the refactor:
- scripts.processing.* service seams are patched on the scripts modules
  (the router imports them lazily at call time, so patches intercept).
- Database seams are patched on app.routers.processing.{get_batch,
  update_batch_status, sync_batch} (names the router keeps referencing).
- settings.CAPTURES_DIR is monkeypatched to tmp_path for disk-state pins.

Known quirks intentionally pinned (do NOT "fix" one side without the other):
- HTTPException(404) raised inside try blocks WITHOUT an `except HTTPException:
  raise` clause resurfaces as 500 with str(exc) as detail, e.g.
  /crop/top-image on an empty batch -> 500 containing "No images found in batch".
- /seamless/analyze blend_width=0 falls back to 128 (`or` quirk).
- /validate/check failing sub-checks (success=False) are excluded from
  all_passed computation.
- Legacy /crop/auto-detect failure returns 200 with success=False and does
  NOT touch batch status.
"""
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: mock heavy hardware modules so importing main.py doesn't fail
# (mirrors test_processing_api.py)
# ---------------------------------------------------------------------------

_camera_mock = MagicMock()
_camera_mock.startup_check.return_value = {"detected": False}
_camera_mock.disconnect.return_value = None

_light_mock = MagicMock()
_light_mock.connect = MagicMock(return_value={"connected": False, "host": "mock"})
_light_mock.disconnect = MagicMock()

sys.modules.setdefault("gphoto2", MagicMock())
sys.modules.setdefault("aiohttp", MagicMock())

_light_mod = types.ModuleType("app.services.light_service")
_light_mod.light_service = _light_mock
sys.modules.setdefault("app.services.light_service", _light_mod)

_APP_IMPORT_ERROR = None
try:
    with patch("app.services.camera_service.camera_service", _camera_mock), \
         patch("app.services.light_service.light_service", _light_mock):
        from main import app
    from fastapi.testclient import TestClient
    from app.config import settings as app_settings
except Exception as exc:  # pragma: no cover
    _APP_IMPORT_ERROR = str(exc)
    app = None
    TestClient = None
    app_settings = None

pytestmark = pytest.mark.skipif(
    _APP_IMPORT_ERROR is not None,
    reason=f"Could not import FastAPI app: {_APP_IMPORT_ERROR}",
)


BATCH = "test_batch"


def _make_client(get_batch_value):
    with patch("app.routers.processing.get_batch") as mock_get_batch, \
         patch("app.routers.processing.update_batch_status") as mock_update, \
         patch("app.routers.processing.sync_batch") as mock_sync:
        mock_get_batch.return_value = get_batch_value
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """TestClient with mocked DB layer; batch exists."""
    yield from _make_client({"name": BATCH, "id": 1})


@pytest.fixture
def client_no_batch():
    """TestClient where get_batch returns None."""
    yield from _make_client(None)


@pytest.fixture
def caps(tmp_path, monkeypatch):
    """Redirect settings.CAPTURES_DIR to tmp_path and make the batch folder."""
    monkeypatch.setattr(app_settings, "CAPTURES_DIR", tmp_path)
    batch = tmp_path / BATCH
    batch.mkdir()
    return tmp_path


def _batch_dir(caps):
    return caps / BATCH


# ---------------------------------------------------------------------------
# CROP: GET /crop/top-image/{batch}
# ---------------------------------------------------------------------------

class TestCropTopImage:

    def test_happy_returns_service_dict_verbatim(self, client, caps):
        svc_dict = {
            "batch_name": BATCH,
            "filename": "mat_top.tiff",
            "width": 8000,
            "height": 6000,
            "preview_url": f"/media/captures/{BATCH}/tiff/mat_top.tiff",
        }
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.get_top_image_for_crop.return_value = svc_dict
            resp = client.get(f"/api/processing/crop/top-image/{BATCH}")

        assert resp.status_code == 200
        assert resp.json() == svc_dict
        crop_cls.return_value.get_top_image_for_crop.assert_called_once_with(
            str(_batch_dir(caps))
        )

    def test_empty_batch_quirk_404_becomes_500(self, client, caps):
        """404 raised inside try is swallowed by `except Exception` -> 500."""
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.get_top_image_for_crop.return_value = None
            resp = client.get(f"/api/processing/crop/top-image/{BATCH}")

        assert resp.status_code == 500
        assert "No images found in batch" in str(resp.json()["detail"])

    def test_service_exception_becomes_500(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.get_top_image_for_crop.side_effect = RuntimeError("boom-top")
            resp = client.get(f"/api/processing/crop/top-image/{BATCH}")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "boom-top"

    def test_batch_folder_missing_404(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(app_settings, "CAPTURES_DIR", tmp_path)
        resp = client.get(f"/api/processing/crop/top-image/{BATCH}")
        assert resp.status_code == 404
        assert resp.json()["detail"].startswith("Batch folder not found: ")

    def test_batch_not_in_db_404(self, client_no_batch, caps):
        resp = client_no_batch.get(f"/api/processing/crop/top-image/{BATCH}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == f"Batch not found: {BATCH}"


# ---------------------------------------------------------------------------
# CROP: POST /crop/auto-detect and /crop/preview-manual
# ---------------------------------------------------------------------------

class TestCropDetectAndPreviewManual:

    def test_auto_detect_happy(self, client, caps):
        svc_dict = {"success": True, "bbox": [10, 20, 3000, 3000], "preview": "x"}
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.auto_detect_crop.return_value = svc_dict
            resp = client.post(
                "/api/processing/crop/auto-detect",
                json={"batch_name": BATCH, "crop_size": 3200},
            )

        assert resp.status_code == 200
        assert resp.json() == svc_dict
        crop_cls.assert_called_once_with(use_gpu=app_settings.USE_GPU)
        crop_cls.return_value.auto_detect_crop.assert_called_once_with(
            str(_batch_dir(caps)), crop_size=3200
        )

    def test_auto_detect_error_500(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.auto_detect_crop.side_effect = RuntimeError("no fabric")
            resp = client.post(
                "/api/processing/crop/auto-detect", json={"batch_name": BATCH}
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "no fabric"

    def test_preview_manual_happy(self, client, caps):
        svc_dict = {"success": True, "preview": "data:image/png;base64,abc"}
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.preview_manual_crop.return_value = svc_dict
            resp = client.post(
                "/api/processing/crop/preview-manual",
                json={"batch_name": BATCH, "bbox": [1, 2, 3, 4]},
            )

        assert resp.status_code == 200
        assert resp.json() == svc_dict
        crop_cls.return_value.preview_manual_crop.assert_called_once_with(
            str(_batch_dir(caps)), [1, 2, 3, 4]
        )

    def test_preview_manual_error_500(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.preview_manual_crop.side_effect = ValueError("bad bbox")
            resp = client.post(
                "/api/processing/crop/preview-manual",
                json={"batch_name": BATCH, "bbox": [1, 2, 3, 4]},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "bad bbox"


# ---------------------------------------------------------------------------
# CROP: POST /crop/apply
# ---------------------------------------------------------------------------

def _crop_results():
    ok = SimpleNamespace(
        success=True, source_path="/x/mat_top.ARW", output_path="/x/mat_top.tiff",
        error=None, bbox=[1, 1, 2, 2],
    )
    bad = SimpleNamespace(
        success=False, source_path="/x/mat_side_1.ARW", output_path=None,
        error="could not open", bbox=None,
    )
    return [ok, bad]


class TestCropApply:

    def test_happy_shape_and_status_flow(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.apply_crop_to_all.return_value = _crop_results()
            with patch("app.routers.processing.get_batch") as gb, \
                 patch("app.routers.processing.update_batch_status") as upd, \
                 patch("app.routers.processing.sync_batch") as sync:
                gb.return_value = {"name": BATCH, "id": 1}
                with TestClient(app) as c:
                    resp = c.post(
                        "/api/processing/crop/apply",
                        json={"batch_name": BATCH, "bbox": [0, 0, 100, 100],
                              "crop_type": "manual", "rotation": 5},
                    )

        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "batch_name": BATCH,
            "crop_type": "manual",
            "rotation": 5,
            "processed": 1,
            "total": 2,
            "results": [
                {"source": "/x/mat_top.ARW", "output": "/x/mat_top.tiff",
                 "success": True, "error": None},
                {"source": "/x/mat_side_1.ARW", "output": None,
                 "success": False, "error": "could not open"},
            ],
        }
        # status: in_progress -> completed (with crop_type), then background sync
        assert [(a, kw) for a, kw in
                [(c.args, c.kwargs) for c in upd.call_args_list]] == [
            ((BATCH, "crop", "in_progress"), {"crop_type": "manual"}),
            ((BATCH, "crop", "completed"), {"crop_type": "manual"}),
        ]
        sync.assert_called_once_with(BATCH)

    def test_points_converted_to_dicts_when_four(self, client, caps):
        points = [
            {"x": 0.0, "y": 0.0}, {"x": 100.0, "y": 0.0},
            {"x": 100.0, "y": 100.0}, {"x": 0.0, "y": 100.0},
        ]
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.apply_crop_to_all.return_value = []
            resp = client.post(
                "/api/processing/crop/apply",
                json={"batch_name": BATCH, "crop_type": "auto", "points": points},
            )

        assert resp.status_code == 200
        assert resp.json()["success"] is False  # zero results -> no successes
        kwargs = crop_cls.return_value.apply_crop_to_all.call_args.kwargs
        assert kwargs == {
            "batch_path": str(_batch_dir(caps)),
            "bbox": None,
            "crop_type": "auto",
            "points": points,
            "rotation": 0,
        }

    def test_points_ignored_when_not_four(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.apply_crop_to_all.return_value = []
            resp = client.post(
                "/api/processing/crop/apply",
                json={"batch_name": BATCH,
                      "points": [{"x": 1.0, "y": 1.0}, {"x": 2.0, "y": 2.0}]},
            )
        assert resp.status_code == 200
        assert crop_cls.return_value.apply_crop_to_all.call_args.kwargs["points"] is None

    def test_all_failed_sets_pending(self, client, caps):
        bad = SimpleNamespace(
            success=False, source_path="/x.ARW", output_path=None,
            error="e", bbox=None,
        )
        with patch("scripts.processing.crop_service.CropService") as crop_cls, \
             patch("app.routers.processing.update_batch_status") as upd:
            crop_cls.return_value.apply_crop_to_all.return_value = [bad]
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/crop/apply",
                    json={"batch_name": BATCH, "bbox": [0, 0, 1, 1]},
                )

        assert resp.status_code == 200
        assert resp.json()["success"] is False
        calls = [(c_.args, c_.kwargs) for c_ in upd.call_args_list]
        assert calls == [
            ((BATCH, "crop", "in_progress"), {"crop_type": "manual"}),
            ((BATCH, "crop", "pending"), {"crop_type": "manual"}),
        ]

    def test_exception_sets_pending_without_crop_type_and_500(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls, \
             patch("app.routers.processing.update_batch_status") as upd:
            crop_cls.return_value.apply_crop_to_all.side_effect = RuntimeError("disk full")
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/crop/apply",
                    json={"batch_name": BATCH, "bbox": [0, 0, 1, 1],
                          "crop_type": "manual"},
                )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "disk full"
        # in_progress was set before the failure; except clause resets to pending
        assert [(c_.args, c_.kwargs) for c_ in upd.call_args_list] == [
            ((BATCH, "crop", "in_progress"), {"crop_type": "manual"}),
            ((BATCH, "crop", "pending"), {}),
        ]


# ---------------------------------------------------------------------------
# CROP: legacy /crop/manual and /crop/auto
# ---------------------------------------------------------------------------

class TestCropLegacy:

    def test_manual_delegates_to_apply(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.apply_crop_to_all.return_value = _crop_results()
            resp = client.post(
                "/api/processing/crop/manual",
                json={"batch_name": BATCH, "bbox": [0, 0, 50, 50]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["crop_type"] == "manual"
        assert body["rotation"] == 0
        assert body["processed"] == 1
        assert body["total"] == 2
        kwargs = crop_cls.return_value.apply_crop_to_all.call_args.kwargs
        assert kwargs["crop_type"] == "manual"
        assert kwargs["bbox"] == [0, 0, 50, 50]
        assert kwargs["points"] is None

    def test_auto_detect_failure_200_false_and_no_status_touch(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls, \
             patch("app.routers.processing.update_batch_status") as upd:
            crop_cls.return_value.auto_detect_crop.return_value = {
                "success": False, "error": "no fabric found"
            }
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/crop/auto", json={"batch_name": BATCH}
                )

        assert resp.status_code == 200
        assert resp.json() == {
            "success": False,
            "batch_name": BATCH,
            "processed": 0,
            "total": 0,
            "error": "no fabric found",
            "results": [],
        }
        upd.assert_not_called()

    def test_auto_happy_includes_bbox_per_result(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls, \
             patch("app.routers.processing.update_batch_status") as upd, \
             patch("app.routers.processing.sync_batch") as sync:
            crop_cls.return_value.auto_detect_crop.return_value = {
                "success": True, "bbox": [5, 6, 700, 700],
            }
            crop_cls.return_value.apply_crop_to_all.return_value = _crop_results()
            with TestClient(app) as c:
                resp = c.post("/api/processing/crop/auto", json={"batch_name": BATCH})

        body = resp.json()
        assert resp.status_code == 200
        assert body["bbox"] == [5, 6, 700, 700]
        assert body["processed"] == 1
        # legacy /crop/auto keeps per-result bbox (unlike /crop/apply)
        assert body["results"][0]["bbox"] == [1, 1, 2, 2]
        assert "bbox" in body["results"][1] and body["results"][1]["bbox"] is None
        assert body["results"][0]["error"] is None
        calls = [(c_.args, c_.kwargs) for c_ in upd.call_args_list]
        assert calls == [
            ((BATCH, "crop", "in_progress"), {"crop_type": "auto"}),
            ((BATCH, "crop", "completed"), {"crop_type": "auto"}),
        ]
        sync.assert_called_once_with(BATCH)

    def test_auto_exception_500_pending_without_crop_type(self, client, caps):
        with patch("scripts.processing.crop_service.CropService") as crop_cls, \
             patch("app.routers.processing.update_batch_status") as upd:
            crop_cls.return_value.auto_detect_crop.side_effect = RuntimeError("sam boom")
            with TestClient(app) as c:
                resp = c.post("/api/processing/crop/auto", json={"batch_name": BATCH})

        assert resp.status_code == 500
        assert resp.json()["detail"] == "sam boom"
        upd.assert_called_once_with(BATCH, "crop", "pending")

    def test_crop_preview_alias_matches_top_image(self, client, caps):
        svc_dict = {"filename": "mat_top.tiff"}
        with patch("scripts.processing.crop_service.CropService") as crop_cls:
            crop_cls.return_value.get_top_image_for_crop.return_value = svc_dict
            resp = client.get(f"/api/processing/crop/preview/{BATCH}")
        assert resp.status_code == 200
        assert resp.json() == svc_dict


# ---------------------------------------------------------------------------
# POST /reconvert-tiff
# ---------------------------------------------------------------------------

class TestReconvertTiff:

    def _raw_dir(self, caps, names=("a.ARW", "b.ARW")):
        raw = _batch_dir(caps) / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        for n in names:
            (raw / n).write_bytes(b"")
        return raw

    def test_path_traversal_400(self, client, caps):
        resp = client.post(
            "/api/processing/reconvert-tiff", json={"path": "../escape"}
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid path"

    def test_folder_not_found_404(self, client, caps):
        resp = client.post(
            "/api/processing/reconvert-tiff", json={"path": "missing_dir"}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Folder not found: missing_dir"

    def test_not_a_directory_404(self, client, caps):
        (caps / "afile.txt").write_text("x")
        resp = client.post(
            "/api/processing/reconvert-tiff", json={"path": "afile.txt"}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Folder not found: afile.txt"

    def test_no_raw_folder_404(self, client, caps):
        _batch_dir(caps).mkdir(exist_ok=True)
        resp = client.post(
            "/api/processing/reconvert-tiff", json={"path": BATCH}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == f"No raw/ folder in {BATCH}"

    def test_happy_two_files(self, client, caps):
        self._raw_dir(caps)
        with patch("scripts.processing.raw_utils.load_raw", return_value="RGB") as lr, \
             patch("scripts.processing.raw_utils.save_tiff", return_value=True) as st:
            resp = client.post(
                "/api/processing/reconvert-tiff", json={"path": BATCH}
            )

        assert resp.status_code == 200
        assert resp.json() == {
            "path": BATCH,
            "fixed_wb": None,
            "success": 2,
            "failed": 0,
            "total": 2,
            "files": [
                {"name": "a.ARW", "status": "ok"},
                {"name": "b.ARW", "status": "ok"},
            ],
        }
        assert st.call_count == 2
        # tiff/ dir was created next to raw/
        assert (_batch_dir(caps) / "tiff").is_dir()

    def test_non_raw_files_skipped(self, client, caps):
        self._raw_dir(caps, names=("a.ARW", "notes.txt"))
        with patch("scripts.processing.raw_utils.load_raw", return_value="RGB"), \
             patch("scripts.processing.raw_utils.save_tiff", return_value=True):
            resp = client.post(
                "/api/processing/reconvert-tiff", json={"path": BATCH}
            )
        body = resp.json()
        assert body["total"] == 1
        assert body["files"] == [{"name": "a.ARW", "status": "ok"}]

    def test_load_raw_none_records_error(self, client, caps):
        self._raw_dir(caps, names=("a.ARW",))
        with patch("scripts.processing.raw_utils.load_raw", return_value=None), \
             patch("scripts.processing.raw_utils.save_tiff") as st:
            resp = client.post(
                "/api/processing/reconvert-tiff", json={"path": BATCH}
            )
        body = resp.json()
        assert body["success"] == 0 and body["failed"] == 1
        assert body["files"] == [
            {"name": "a.ARW", "status": "error", "error": "RAW loading returned None"}
        ]
        st.assert_not_called()

    def test_save_tiff_false_records_error(self, client, caps):
        self._raw_dir(caps, names=("a.ARW",))
        with patch("scripts.processing.raw_utils.load_raw", return_value="RGB"), \
             patch("scripts.processing.raw_utils.save_tiff", return_value=False):
            resp = client.post(
                "/api/processing/reconvert-tiff", json={"path": BATCH}
            )
        body = resp.json()
        assert body["files"][0]["error"] == "TIFF save failed"

    def test_checker_raw_missing_404(self, client, caps):
        self._raw_dir(caps)
        resp = client.post(
            "/api/processing/reconvert-tiff",
            json={"path": BATCH, "checker_raw_path": "/nope/checker.ARW"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Checker RAW not found: /nope/checker.ARW"

    def test_checker_wb_extract_none_500(self, client, caps):
        self._raw_dir(caps)
        checker = caps / "checker.ARW"
        checker.write_bytes(b"")
        with patch("scripts.processing.raw_utils.extract_wb", return_value=None):
            resp = client.post(
                "/api/processing/reconvert-tiff",
                json={"path": BATCH, "checker_raw_path": str(checker)},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == f"Could not extract WB from {checker}"

    def test_fixed_wb_uses_fixed_loader(self, client, caps):
        self._raw_dir(caps, names=("a.ARW",))
        checker = caps / "checker.ARW"
        checker.write_bytes(b"")
        wb = [2.0, 1.0, 1.0]
        with patch("scripts.processing.raw_utils.extract_wb", return_value=wb) as ew, \
             patch("scripts.processing.raw_utils.load_raw_with_fixed_wb",
                   return_value="RGB") as lrf, \
             patch("scripts.processing.raw_utils.load_raw") as lr, \
             patch("scripts.processing.raw_utils.save_tiff", return_value=True):
            resp = client.post(
                "/api/processing/reconvert-tiff",
                json={"path": BATCH, "checker_raw_path": str(checker)},
            )

        body = resp.json()
        assert body["fixed_wb"] == wb
        assert body["success"] == 1
        ew.assert_called_once_with(checker)
        lrf.assert_called_once()
        lr.assert_not_called()


# ---------------------------------------------------------------------------
# ColorChecker: POST /colorchecker/detect, GET /colorchecker/profiles
# ---------------------------------------------------------------------------

class TestColorcheckerDetect:

    def _checker(self):
        return SimpleNamespace(source_image="/imgs/checker.jpg",
                               detected_swatches=list(range(24)))

    def test_image_missing_404(self, client, caps):
        resp = client.post(
            "/api/processing/colorchecker/detect",
            json={"image_path": "/nope/checker.jpg"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Image not found: /nope/checker.jpg"

    def test_colour_unavailable_500(self, client, caps):
        img = caps / "checker.jpg"
        img.write_bytes(b"")
        with patch("scripts.processing.calibration_service.CalibrationService"), \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", False):
            resp = client.post(
                "/api/processing/colorchecker/detect",
                json={"image_path": str(img)},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == (
            "colour-science library not installed. "
            "Run: pip install colour-science colour-checker-detection"
        )

    def test_happy_shape(self, client, caps):
        img = caps / "checker.jpg"
        img.write_bytes(b"")
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.detect_colorchecker.return_value = self._checker()
            resp = client.post(
                "/api/processing/colorchecker/detect",
                json={"image_path": str(img)},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "source_image": "/imgs/checker.jpg",
            "swatches_detected": 24,
        }

    def test_save_profile_adds_profile_fields(self, client, caps):
        img = caps / "checker.jpg"
        img.write_bytes(b"")
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.detect_colorchecker.return_value = self._checker()
            cls_.return_value.save_colorchecker_profile.return_value = "/prof.npz"
            resp = client.post(
                "/api/processing/colorchecker/detect",
                json={"image_path": str(img), "save_profile": True,
                      "profile_name": "CHECKER-1"},
            )
        body = resp.json()
        assert body["profile_saved"] is True
        assert body["profile_path"] == "/prof.npz"
        cls_.return_value.save_colorchecker_profile.assert_called_once()

    def test_save_without_name_skips_profile(self, client, caps):
        img = caps / "checker.jpg"
        img.write_bytes(b"")
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.detect_colorchecker.return_value = self._checker()
            resp = client.post(
                "/api/processing/colorchecker/detect",
                json={"image_path": str(img), "save_profile": True},
            )
        assert "profile_saved" not in resp.json()
        cls_.return_value.save_colorchecker_profile.assert_not_called()

    def test_none_detection_404_becomes_500_quirk(self, client, caps):
        img = caps / "checker.jpg"
        img.write_bytes(b"")
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.detect_colorchecker.return_value = None
            resp = client.post(
                "/api/processing/colorchecker/detect",
                json={"image_path": str(img)},
            )
        assert resp.status_code == 500
        assert "No ColorChecker detected in image" in str(resp.json()["detail"])

    def test_import_error_specific_500(self, client, caps):
        img = caps / "checker.jpg"
        img.write_bytes(b"")
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.detect_colorchecker.side_effect = ImportError("no colour")
            resp = client.post(
                "/api/processing/colorchecker/detect",
                json={"image_path": str(img)},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "CalibrationService not available: no colour"

    def test_generic_error_500(self, client, caps):
        img = caps / "checker.jpg"
        img.write_bytes(b"")
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.detect_colorchecker.side_effect = RuntimeError("bad img")
            resp = client.post(
                "/api/processing/colorchecker/detect",
                json={"image_path": str(img)},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "bad img"


class TestColorcheckerProfiles:

    def test_unavailable_returns_warning_200(self, client, caps):
        with patch("scripts.processing.calibration_service.CalibrationService"), \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", False):
            resp = client.get("/api/processing/colorchecker/profiles")
        assert resp.status_code == 200
        assert resp.json() == {
            "profiles": [],
            "warning": "colour-science library not installed",
        }

    def test_happy_lists_profiles(self, client, caps):
        profiles = [{"name": "P1", "created": "2026-01-01"}]
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.list_profiles.return_value = profiles
            resp = client.get("/api/processing/colorchecker/profiles")
        assert resp.status_code == 200
        assert resp.json() == {"profiles": profiles}

    def test_error_returns_error_field_200(self, client, caps):
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.list_profiles.side_effect = RuntimeError("fs")
            resp = client.get("/api/processing/colorchecker/profiles")
        assert resp.status_code == 200
        assert resp.json() == {"profiles": [], "error": "fs"}


# ---------------------------------------------------------------------------
# POST /calibrate
# ---------------------------------------------------------------------------

def _cal_results():
    ok = SimpleNamespace(success=True, source_path="/s/1.tiff",
                         output_path="/o/1.tiff", error=None)
    bad = SimpleNamespace(success=False, source_path="/s/2.tiff",
                          output_path=None, error="dark")
    return [ok, bad]


class TestCalibrate:

    def test_requires_profile_or_image_400(self, client, caps):
        resp = client.post(
            "/api/processing/calibrate", json={"batch_name": BATCH}
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == (
            "Must provide either profile_name or colorchecker_image"
        )

    def test_profile_not_found_404_passthrough(self, client, caps):
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.load_colorchecker_profile.return_value = None
            resp = client.post(
                "/api/processing/calibrate",
                json={"batch_name": BATCH, "profile_name": "GONE"},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Profile not found: GONE"

    def test_colour_unavailable_500(self, client, caps):
        with patch("scripts.processing.calibration_service.CalibrationService"), \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", False):
            resp = client.post(
                "/api/processing/calibrate",
                json={"batch_name": BATCH, "profile_name": "P1"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "colour-science library not installed"

    def test_checker_image_missing_404_passthrough(self, client, caps):
        with patch("scripts.processing.calibration_service.CalibrationService"), \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            resp = client.post(
                "/api/processing/calibrate",
                json={"batch_name": BATCH, "colorchecker_image": "/nope.jpg"},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "ColorChecker image not found: /nope.jpg"

    def test_checker_image_undetected_400_passthrough(self, client, caps):
        img = caps / "checker.jpg"
        img.write_bytes(b"")
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.detect_colorchecker.return_value = None
            resp = client.post(
                "/api/processing/calibrate",
                json={"batch_name": BATCH, "colorchecker_image": str(img)},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "No ColorChecker detected in provided image"

    def test_profile_happy_shape_and_status_flow(self, client, caps):
        checker = SimpleNamespace(source_image="/c")
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True), \
             patch("app.routers.processing.update_batch_status") as upd, \
             patch("app.routers.processing.sync_batch") as sync:
            cls_.return_value.load_colorchecker_profile.return_value = checker
            cls_.return_value.calibrate_batch.return_value = _cal_results()
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/calibrate",
                    json={"batch_name": BATCH, "profile_name": "PROF",
                          "checker_raw_path": "/raw/checker.ARW"},
                )

        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "batch_name": BATCH,
            "processed": 1,
            "total": 2,
            "results": [
                {"source": "/s/1.tiff", "output": "/o/1.tiff",
                 "success": True, "error": None},
                {"source": "/s/2.tiff", "output": None,
                 "success": False, "error": "dark"},
            ],
        }
        cls_.return_value.calibrate_batch.assert_called_once_with(
            batch_path=str(_batch_dir(caps)),
            checker_data=checker,
            checker_raw_path="/raw/checker.ARW",
        )
        calls = [(c_.args, c_.kwargs) for c_ in upd.call_args_list]
        assert calls == [
            ((BATCH, "calibration", "in_progress"), {}),
            ((BATCH, "calibration", "completed"), {}),
        ]
        sync.assert_called_once_with(BATCH)

    def test_all_failed_sets_pending(self, client, caps):
        bad = SimpleNamespace(success=False, source_path="/s", output_path=None,
                              error="x")
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True), \
             patch("app.routers.processing.update_batch_status") as upd:
            cls_.return_value.load_colorchecker_profile.return_value = SimpleNamespace()
            cls_.return_value.calibrate_batch.return_value = [bad]
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/calibrate",
                    json={"batch_name": BATCH, "profile_name": "PROF"},
                )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        upd.assert_called_with(BATCH, "calibration", "pending")

    def test_exception_sets_pending_and_500(self, client, caps):
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True), \
             patch("app.routers.processing.update_batch_status") as upd:
            cls_.return_value.load_colorchecker_profile.return_value = SimpleNamespace()
            cls_.return_value.calibrate_batch.side_effect = RuntimeError("matrix")
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/calibrate",
                    json={"batch_name": BATCH, "profile_name": "PROF"},
                )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "matrix"
        assert [(c_.args, c_.kwargs) for c_ in upd.call_args_list] == [
            ((BATCH, "calibration", "in_progress"), {}),
            ((BATCH, "calibration", "pending"), {}),
        ]


class TestCalibratePreview:

    def test_unavailable_500(self, client, caps):
        with patch("scripts.processing.calibration_service.CalibrationService"), \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", False):
            resp = client.get(f"/api/processing/calibrate/preview/{BATCH}")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "colour-science not available"

    def test_happy(self, client, caps):
        preview = {"before": "/b.jpg", "after": "/a.jpg"}
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.get_preview_comparison.return_value = preview
            resp = client.get(f"/api/processing/calibrate/preview/{BATCH}")
        assert resp.status_code == 200
        assert resp.json() == preview

    def test_none_becomes_500_quirk(self, client, caps):
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.get_preview_comparison.return_value = None
            resp = client.get(f"/api/processing/calibrate/preview/{BATCH}")
        assert resp.status_code == 500
        assert "No preview available" in str(resp.json()["detail"])

    def test_error_500(self, client, caps):
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.get_preview_comparison.side_effect = RuntimeError("io")
            resp = client.get(f"/api/processing/calibrate/preview/{BATCH}")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "io"


# ---------------------------------------------------------------------------
# POST /pbr
# ---------------------------------------------------------------------------

class TestPbr:

    def _pbr_result(self, success=True):
        return SimpleNamespace(success=success, images_processed=9,
                               outputs=["albedo.png"], error=None)

    def test_invalid_mode_400(self, client, caps):
        resp = client.post(
            "/api/processing/pbr",
            json={"batch_name": BATCH, "mode": "turbo"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid mode: turbo"

    def test_happy_shape_and_status_flow(self, client, caps):
        with patch("scripts.processing.pbr_service.PBRService") as cls_, \
             patch("app.routers.processing.update_batch_status") as upd, \
             patch("app.routers.processing.sync_batch") as sync:
            cls_.return_value.generate.return_value = self._pbr_result()
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/pbr",
                    json={"batch_name": BATCH, "mode": "grayscale"},
                )

        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "batch_name": BATCH,
            "mode": "grayscale",
            "images_processed": 9,
            "outputs": ["albedo.png"],
            "error": None,
        }
        calls = [(c_.args, c_.kwargs) for c_ in upd.call_args_list]
        assert calls == [
            ((BATCH, "pbr", "in_progress"), {"pbr_mode": "grayscale"}),
            ((BATCH, "pbr", "completed"), {"pbr_mode": "grayscale"}),
        ]
        sync.assert_called_once_with(BATCH)

    def test_failure_result_sets_pending(self, client, caps):
        with patch("scripts.processing.pbr_service.PBRService") as cls_, \
             patch("app.routers.processing.update_batch_status") as upd:
            cls_.return_value.generate.return_value = self._pbr_result(success=False)
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/pbr",
                    json={"batch_name": BATCH, "mode": "colored"},
                )
        body = resp.json()
        assert body["success"] is False
        upd.assert_called_with(BATCH, "pbr", "pending", pbr_mode="colored")

    def test_exception_sets_pending_without_mode_and_500(self, client, caps):
        with patch("scripts.processing.pbr_service.PBRService") as cls_, \
             patch("app.routers.processing.update_batch_status") as upd:
            cls_.return_value.generate.side_effect = RuntimeError("stereo")
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/pbr",
                    json={"batch_name": BATCH, "mode": "both"},
                )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "stereo"
        assert [(c_.args, c_.kwargs) for c_ in upd.call_args_list] == [
            ((BATCH, "pbr", "in_progress"), {"pbr_mode": "both"}),
            ((BATCH, "pbr", "pending"), {}),
        ]

    def test_selected_images_passthrough(self, client, caps):
        with patch("scripts.processing.pbr_service.PBRService") as cls_:
            cls_.return_value.generate.return_value = self._pbr_result()
            resp = client.post(
                "/api/processing/pbr",
                json={"batch_name": BATCH, "mode": "grayscale",
                      "selected_images": ["top"]},
            )
        cls_.return_value.generate.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), mode="grayscale",
            selected_images=["top"],
        )


class TestPbrPreview:

    def test_nothing_generated_404(self, client, caps):
        resp = client.get(f"/api/processing/pbr/preview/{BATCH}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "No PBR maps generated yet"

    def test_grayscale_png_only(self, client, caps):
        folder = _batch_dir(caps) / "pbr_grayscale"
        folder.mkdir()
        (folder / "albedo.png").write_bytes(b"")
        resp = client.get(f"/api/processing/pbr/preview/{BATCH}")
        assert resp.status_code == 200
        assert resp.json() == {
            "batch_name": BATCH,
            "grayscale": {"albedo": f"/media/captures/{BATCH}/pbr_grayscale/albedo.png"},
            "colored": None,
        }

    def test_png_preferred_over_tiff(self, client, caps):
        folder = _batch_dir(caps) / "pbr_grayscale"
        folder.mkdir()
        (folder / "albedo.png").write_bytes(b"")
        (folder / "albedo.tiff").write_bytes(b"")
        resp = client.get(f"/api/processing/pbr/preview/{BATCH}")
        assert resp.json()["grayscale"] == {
            "albedo": f"/media/captures/{BATCH}/pbr_grayscale/albedo.png"
        }

    def test_tiff_fallback_and_colored(self, client, caps):
        gs = _batch_dir(caps) / "pbr_grayscale"
        gs.mkdir()
        (gs / "normals.tiff").write_bytes(b"")
        colored = _batch_dir(caps) / "pbr_colored"
        colored.mkdir()
        (colored / "height_map.png").write_bytes(b"")
        resp = client.get(f"/api/processing/pbr/preview/{BATCH}")
        body = resp.json()
        assert body["grayscale"] == {
            "normals": f"/media/captures/{BATCH}/pbr_grayscale/normals.tiff"
        }
        assert body["colored"] == {
            "height_map": f"/media/captures/{BATCH}/pbr_colored/height_map.png"
        }


# ---------------------------------------------------------------------------
# GET /status/{batch} and GET /tools/status/{batch}
# ---------------------------------------------------------------------------

class TestProcessingStatus:

    def test_defaults_with_empty_folders(self, client, caps):
        resp = client.get(f"/api/processing/status/{BATCH}")
        assert resp.status_code == 200
        assert resp.json() == {
            "batch_name": BATCH,
            "crop_status": "pending",
            "crop_type": None,
            "calibration_status": "pending",
            "pbr_status": "pending",
            "pbr_mode": None,
            "folders": {
                "tiff": False, "raw": False, "cropped": False,
                "color_calibrated": False, "pbr_grayscale": False,
                "pbr_colored": False,
            },
        }

    def test_statuses_from_db_and_folders_from_disk(self, client, caps):
        for f in ("tiff", "raw"):
            (_batch_dir(caps) / f).mkdir()
        with patch("app.routers.processing.get_batch") as gb:
            gb.return_value = {
                "name": BATCH,
                "crop_status": "completed",
                "crop_type": "auto",
                "calibration_status": "completed",
                "pbr_status": "in_progress",
                "pbr_mode": "grayscale",
            }
            with TestClient(app) as c:
                resp = c.get(f"/api/processing/status/{BATCH}")
        body = resp.json()
        assert body["crop_status"] == "completed"
        assert body["crop_type"] == "auto"
        assert body["pbr_mode"] == "grayscale"
        assert body["folders"]["tiff"] is True
        assert body["folders"]["cropped"] is False


class TestToolsStatus:

    def test_all_absent(self, client, caps):
        resp = client.get(f"/api/processing/tools/status/{BATCH}")
        assert resp.status_code == 200
        assert resp.json() == {
            "batch_name": BATCH,
            "perspective_corrected": False,
            "equalized": False,
            "flattened": False,
            "delighted": False,
            "seamless": False,
            "tiled": False,
        }

    def test_nonempty_folder_true_empty_folder_false(self, client, caps):
        eq = _batch_dir(caps) / "equalized"
        eq.mkdir()
        (eq / "a.tiff").write_bytes(b"")
        (_batch_dir(caps) / "flattened").mkdir()  # exists but empty
        resp = client.get(f"/api/processing/tools/status/{BATCH}")
        body = resp.json()
        assert body["equalized"] is True
        assert body["flattened"] is False

    def test_output_subfolder_counts(self, client, caps):
        out = _batch_dir(caps) / "output" / "tiled"
        out.mkdir(parents=True)
        (out / "a.png").write_bytes(b"")
        resp = client.get(f"/api/processing/tools/status/{BATCH}")
        assert resp.json()["tiled"] is True


# ---------------------------------------------------------------------------
# GET /{tool}/image/{batch}
# ---------------------------------------------------------------------------

class TestToolImage:

    def test_no_source_folders_404(self, client, caps):
        resp = client.get(f"/api/processing/equalize/image/{BATCH}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "No source images found for this tool"

    def test_empty_source_folder_404(self, client, caps):
        (_batch_dir(caps) / "tiff").mkdir()
        resp = client.get(f"/api/processing/equalize/image/{BATCH}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "No source images found for this tool"

    def test_tiff_fallback_and_url_fallback(self, client, caps):
        tiff = _batch_dir(caps) / "tiff"
        tiff.mkdir()
        (tiff / "material_side_1.tiff").write_bytes(b"")
        (tiff / "material_top.tiff").write_bytes(b"")
        resp = client.get(f"/api/processing/equalize/image/{BATCH}")
        assert resp.status_code == 200
        assert resp.json() == {
            "batch_name": BATCH,
            "source_folder": "tiff",
            "filename": "material_top.tiff",
            "preview_url": f"/media/captures/{BATCH}/tiff/material_top.tiff",
            "image_count": 2,
            "images": ["material_side_1.tiff", "material_top.tiff"],
        }

    def test_priority_skips_to_first_nonempty(self, client, caps):
        # equalize priority: color_calibrated, cropped, tiff — only cropped exists
        cropped = _batch_dir(caps) / "cropped"
        cropped.mkdir()
        (cropped / "mat_top.tiff").write_bytes(b"")
        resp = client.get(f"/api/processing/equalize/image/{BATCH}")
        assert resp.json()["source_folder"] == "cropped"

    def test_thumbnail_url_preferred(self, client, caps):
        tiff = _batch_dir(caps) / "tiff"
        tiff.mkdir()
        (tiff / "mat_top.tiff").write_bytes(b"")
        thumbs = _batch_dir(caps) / "tiff_thumbnail"
        thumbs.mkdir()
        (thumbs / "mat_top.jpg").write_bytes(b"")
        resp = client.get(f"/api/processing/equalize/image/{BATCH}")
        assert resp.json()["preview_url"] == (
            f"/media/captures/{BATCH}/tiff_thumbnail/mat_top.jpg"
        )

    def test_full_webview_then_generic_thumbnail(self, client, caps):
        tiff = _batch_dir(caps) / "tiff"
        tiff.mkdir()
        (tiff / "mat_top.tiff").write_bytes(b"")
        wv = _batch_dir(caps) / "full_webview"
        wv.mkdir()
        (wv / "mat_top.jpg").write_bytes(b"")
        gen = _batch_dir(caps) / "thumbnail"
        gen.mkdir()
        (gen / "mat_top.jpg").write_bytes(b"")
        resp = client.get(f"/api/processing/equalize/image/{BATCH}")
        assert resp.json()["preview_url"] == (
            f"/media/captures/{BATCH}/full_webview/mat_top.jpg"
        )

    def test_no_top_named_file_uses_first_sorted(self, client, caps):
        tiff = _batch_dir(caps) / "tiff"
        tiff.mkdir()
        (tiff / "a_first.tiff").write_bytes(b"")
        (tiff / "b_second.tiff").write_bytes(b"")
        resp = client.get(f"/api/processing/equalize/image/{BATCH}")
        assert resp.json()["filename"] == "a_first.tiff"


# ---------------------------------------------------------------------------
# Material tools: equalize / delight / flatten
# ---------------------------------------------------------------------------

class TestEqualizeEndpoints:

    def test_preview_kwargs_and_verbatim_result(self, client, caps):
        sentinel = {"ok": True, "action": "equalize_preview"}
        with patch("scripts.processing.equalize_service.preview",
                   return_value=sentinel) as pv:
            resp = client.post(
                "/api/processing/equalize/preview",
                json={"batch_name": BATCH, "method": "clahe",
                      "reference_image": "ref.tiff", "clip_limit": 3.5},
            )
        assert resp.status_code == 200
        assert resp.json() == sentinel
        pv.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), method="clahe",
            reference_image="ref.tiff", clip_limit=3.5,
        )

    def test_preview_error_500(self, client, caps):
        with patch("scripts.processing.equalize_service.preview",
                   side_effect=RuntimeError("eq fail")):
            resp = client.post(
                "/api/processing/equalize/preview",
                json={"batch_name": BATCH},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "eq fail"

    def test_apply_verbatim_and_sync(self, client, caps):
        sentinel = {"applied": 9}
        with patch("scripts.processing.equalize_service.apply",
                   return_value=sentinel) as ap, \
             patch("app.routers.processing.sync_batch") as sync:
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/equalize/apply",
                    json={"batch_name": BATCH, "apply_to_all": True},
                )
        assert resp.status_code == 200
        assert resp.json() == sentinel
        ap.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), method="clahe",
            reference_image=None, clip_limit=2.0,
        )
        sync.assert_called_once_with(BATCH)


class TestDelightEndpoints:

    def test_preview_kwargs(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.delight_service.preview",
                   return_value=sentinel) as pv:
            resp = client.post(
                "/api/processing/delight/preview",
                json={"batch_name": BATCH, "blur_radius": 300,
                      "strength": 0.5, "method": "frequency_separation"},
            )
        assert resp.json() == sentinel
        pv.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), blur_radius=300,
            strength=0.5, method="frequency_separation",
        )

    def test_apply_and_sync(self, client, caps):
        sentinel = {"applied": 9}
        with patch("scripts.processing.delight_service.apply",
                   return_value=sentinel) as ap, \
             patch("app.routers.processing.sync_batch") as sync:
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/delight/apply",
                    json={"batch_name": BATCH},
                )
        assert resp.json() == sentinel
        ap.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), blur_radius=200,
            strength=1.0, method="gaussian",
        )
        sync.assert_called_once_with(BATCH)


class TestFlattenEndpoints:

    def test_preview_kwargs(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.flatten_service.preview",
                   return_value=sentinel) as pv:
            resp = client.post(
                "/api/processing/flatten/preview",
                json={"batch_name": BATCH, "strength": 0.7,
                      "smoothing_radius": 5, "pbr_mode": "color"},
            )
        assert resp.json() == sentinel
        pv.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), strength=0.7,
            smoothing_radius=5, pbr_mode="color",
        )

    def test_apply_and_sync(self, client, caps):
        sentinel = {"applied": 9}
        with patch("scripts.processing.flatten_service.apply",
                   return_value=sentinel) as ap, \
             patch("app.routers.processing.sync_batch") as sync:
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/flatten/apply",
                    json={"batch_name": BATCH},
                )
        assert resp.json() == sentinel
        ap.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), strength=1.0,
            smoothing_radius=0, pbr_mode="grayscale",
        )
        sync.assert_called_once_with(BATCH)


# ---------------------------------------------------------------------------
# Perspective
# ---------------------------------------------------------------------------

class TestPerspectiveEndpoints:

    def test_detect_lines_injects_batch_name(self, client, caps):
        tiff = _batch_dir(caps) / "tiff"
        tiff.mkdir()
        (tiff / "mat_top.tiff").write_bytes(b"")
        sentinel = {"lines": [1, 2]}
        with patch("scripts.processing.perspective_service.detect_lines",
                   return_value=sentinel) as dl:
            resp = client.post(
                "/api/processing/perspective/detect-lines",
                json={"batch_name": BATCH},
            )
        assert resp.status_code == 200
        assert resp.json() == {"lines": [1, 2], "batch_name": BATCH}
        dl.assert_called_once_with(image_path=tiff / "mat_top.tiff")

    def test_detect_lines_no_images_404_passthrough(self, client, caps):
        resp = client.post(
            "/api/processing/perspective/detect-lines",
            json={"batch_name": BATCH},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "No source images found for this tool"

    def test_preview_converts_points_and_passes_path(self, client, caps):
        sentinel = {"ok": True}
        src = [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0},
               {"x": 1.0, "y": 1.0}, {"x": 0.0, "y": 1.0}]
        dst = [{"x": 5.0, "y": 5.0}, {"x": 6.0, "y": 5.0},
               {"x": 6.0, "y": 6.0}, {"x": 5.0, "y": 6.0}]
        with patch("scripts.processing.perspective_service.preview",
                   return_value=sentinel) as pv:
            resp = client.post(
                "/api/processing/perspective/preview",
                json={"batch_name": BATCH,
                      "source_points": src, "dest_points": dst},
            )
        assert resp.json() == sentinel
        pv.assert_called_once_with(
            batch_path=_batch_dir(caps), source_points=src, dest_points=dst,
        )

    def test_preview_without_dest_points(self, client, caps):
        src = [{"x": 0.0, "y": 0.0}]
        with patch("scripts.processing.perspective_service.preview",
                   return_value={}) as pv:
            resp = client.post(
                "/api/processing/perspective/preview",
                json={"batch_name": BATCH, "source_points": src},
            )
        assert resp.status_code == 200
        pv.assert_called_once_with(
            batch_path=_batch_dir(caps), source_points=src, dest_points=None,
        )

    def test_apply_and_sync(self, client, caps):
        sentinel = {"warped": 9}
        src = [{"x": 1.0, "y": 1.0}]
        with patch("scripts.processing.perspective_service.apply",
                   return_value=sentinel) as ap, \
             patch("app.routers.processing.sync_batch") as sync:
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/perspective/apply",
                    json={"batch_name": BATCH, "source_points": src},
                )
        assert resp.json() == sentinel
        ap.assert_called_once_with(
            batch_path=_batch_dir(caps), source_points=src, dest_points=None,
        )
        sync.assert_called_once_with(BATCH)


# ---------------------------------------------------------------------------
# Seamless
# ---------------------------------------------------------------------------

class TestSeamlessEndpoints:

    def test_analyze_defaults_blend_width_and_injects_batch(self, client, caps):
        tiff = _batch_dir(caps) / "tiff"
        tiff.mkdir()
        (tiff / "mat_top.tiff").write_bytes(b"")
        sentinel = {"max_diff": 12}
        with patch("scripts.processing.seamless_service.analyze_seams",
                   return_value=sentinel) as ans:
            resp = client.post(
                "/api/processing/seamless/analyze",
                json={"batch_name": BATCH, "blend_width": 0},  # 0 -> 128 quirk
            )
        assert resp.status_code == 200
        assert resp.json() == {"max_diff": 12, "batch_name": BATCH}
        ans.assert_called_once_with(
            image_path=tiff / "mat_top.tiff", blend_width=128,
        )

    def test_analyze_explicit_blend_width_kept(self, client, caps):
        tiff = _batch_dir(caps) / "tiff"
        tiff.mkdir()
        (tiff / "mat_top.tiff").write_bytes(b"")
        with patch("scripts.processing.seamless_service.analyze_seams",
                   return_value={}) as ans:
            client.post(
                "/api/processing/seamless/analyze",
                json={"batch_name": BATCH, "blend_width": 64},
            )
        ans.assert_called_once_with(
            image_path=tiff / "mat_top.tiff", blend_width=64,
        )

    def test_analyze_no_images_404(self, client, caps):
        resp = client.post(
            "/api/processing/seamless/analyze", json={"batch_name": BATCH}
        )
        assert resp.status_code == 404

    def test_preview_kwargs(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.seamless_service.preview",
                   return_value=sentinel) as pv:
            resp = client.post(
                "/api/processing/seamless/preview",
                json={"batch_name": BATCH, "method": "mirror",
                      "spots_removal": True, "color_equalizer": 3,
                      "tile_count": 4},
            )
        assert resp.json() == sentinel
        pv.assert_called_once_with(
            batch_path=_batch_dir(caps), method="mirror", blend_width=64,
            spots_removal=True, color_equalizer=3, tile_count=4,
        )

    def test_apply_and_sync(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.seamless_service.apply",
                   return_value=sentinel) as ap, \
             patch("app.routers.processing.sync_batch") as sync:
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/seamless/apply",
                    json={"batch_name": BATCH},
                )
        assert resp.json() == sentinel
        ap.assert_called_once_with(
            batch_path=_batch_dir(caps), method="overlay", blend_width=64,
            spots_removal=False, color_equalizer=0,
        )
        sync.assert_called_once_with(BATCH)


# ---------------------------------------------------------------------------
# Tile
# ---------------------------------------------------------------------------

class TestTileEndpoints:

    def test_preview_kwargs(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.tile_service.preview",
                   return_value=sentinel) as pv:
            resp = client.post(
                "/api/processing/tile/preview",
                json={"batch_name": BATCH, "tile_x": 3, "tile_y": 4,
                      "offset_x": 0.5, "offset_y": 1.5, "scale": 2.0,
                      "rotation": 45.0, "overlap": 0.1, "half_drop": True},
            )
        assert resp.json() == sentinel
        pv.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), tile_x=3, tile_y=4,
            offset_x=0.5, offset_y=1.5, scale=2.0, rotation=45.0,
            overlap=0.1, half_drop=True,
        )

    def test_apply_default_resolution_tuple(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.tile_service.apply",
                   return_value=sentinel) as ap, \
             patch("app.routers.processing.sync_batch") as sync:
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/tile/apply",
                    json={"batch_name": BATCH},
                )
        assert resp.json() == sentinel
        ap.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), tile_x=2, tile_y=2,
            offset_x=0.0, offset_y=0.0, scale=1.0, rotation=0.0,
            overlap=0.0, half_drop=False, output_resolution=(2048, 2048),
        )
        sync.assert_called_once_with(BATCH)

    def test_apply_explicit_resolution_tuple(self, client, caps):
        with patch("scripts.processing.tile_service.apply", return_value={}) as ap:
            client.post(
                "/api/processing/tile/apply",
                json={"batch_name": BATCH, "output_resolution": [4096, 4096]},
            )
        assert ap.call_args.kwargs["output_resolution"] == (4096, 4096)


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

class TestValidateEndpoints:

    def test_check_happy_shape(self, client, caps):
        albedo = {"success": True, "passed": True, "mean": 128.5}
        metal = {"success": True, "passed": False, "ratio": 0.25}
        with patch("scripts.processing.validate_service.validate_albedo",
                   return_value=albedo) as va, \
             patch("scripts.processing.validate_service.validate_metallic",
                   return_value=metal) as vm:
            resp = client.post(
                "/api/processing/validate/check",
                json={"batch_name": BATCH, "albedo_dark_threshold": 30.0},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "batch_name": BATCH,
            "checks": [
                {"map": "albedo", "success": True, "passed": True, "mean": 128.5},
                {"map": "metallic", "success": True, "passed": False, "ratio": 0.25},
            ],
            "all_passed": False,
        }
        va.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), dark_threshold=30,
        )
        vm.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), metal_range=(180, 255),
        )

    def test_check_metal_range_passthrough_tuple(self, client, caps):
        with patch("scripts.processing.validate_service.validate_albedo",
                   return_value={"success": True, "passed": True}), \
             patch("scripts.processing.validate_service.validate_metallic",
                   return_value={"success": True, "passed": True}) as vm:
            client.post(
                "/api/processing/validate/check",
                json={"batch_name": BATCH, "metal_range": [200.0, 255.0]},
            )
        assert vm.call_args.kwargs["metal_range"] == (200.0, 255.0)

    def test_check_failed_subcheck_excluded_from_all_passed(self, client, caps):
        albedo = {"success": False, "passed": False, "err": "no albedo"}
        metal = {"success": True, "passed": True}
        with patch("scripts.processing.validate_service.validate_albedo",
                   return_value=albedo), \
             patch("scripts.processing.validate_service.validate_metallic",
                   return_value=metal):
            resp = client.post(
                "/api/processing/validate/check",
                json={"batch_name": BATCH},
            )
        assert resp.json()["all_passed"] is True  # failed check excluded

    def test_check_error_500(self, client, caps):
        with patch("scripts.processing.validate_service.validate_albedo",
                   side_effect=RuntimeError("no maps")):
            resp = client.post(
                "/api/processing/validate/check",
                json={"batch_name": BATCH},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "no maps"

    def test_stats_injects_batch_name(self, client, caps):
        sentinel = {"albedo_mean": 100}
        with patch("scripts.processing.validate_service.get_stats",
                   return_value=sentinel) as gs:
            resp = client.get(f"/api/processing/validate/stats/{BATCH}")
        assert resp.status_code == 200
        assert resp.json() == {"albedo_mean": 100, "batch_name": BATCH}
        gs.assert_called_once_with(batch_path=str(_batch_dir(caps)))

    def test_stats_error_500(self, client, caps):
        with patch("scripts.processing.validate_service.get_stats",
                   side_effect=RuntimeError("io")):
            resp = client.get(f"/api/processing/validate/stats/{BATCH}")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "io"


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------

class TestCloneEndpoints:

    def test_inpaint_kwargs(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.clone_service.preview_inpaint",
                   return_value=sentinel) as pi:
            resp = client.post(
                "/api/processing/clone/inpaint",
                json={"batch_name": BATCH, "mask_data": "b64==",
                      "method": "ns", "radius": 7},
            )
        assert resp.json() == sentinel
        pi.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), mask_data_b64="b64==",
            method="ns", radius=7,
        )

    def test_stamp_converts_positions_to_dicts(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.clone_service.preview_stamp",
                   return_value=sentinel) as ps:
            resp = client.post(
                "/api/processing/clone/stamp",
                json={"batch_name": BATCH,
                      "source_pos": {"x": 1.5, "y": 2.5},
                      "target_pos": {"x": 3.5, "y": 4.5},
                      "radius": 60, "fade": 0.8, "blur_mask": 1.2,
                      "mirror": True},
            )
        assert resp.json() == sentinel
        ps.assert_called_once_with(
            batch_path=str(_batch_dir(caps)),
            source_pos={"x": 1.5, "y": 2.5},
            target_pos={"x": 3.5, "y": 4.5},
            radius=60, fade=0.8, blur_mask=1.2, mirror=True,
        )

    def test_apply_and_sync(self, client, caps):
        sentinel = {"applied": 3}
        ops = [{"op": "inpaint", "mask": "x"}]
        with patch("scripts.processing.clone_service.apply",
                   return_value=sentinel) as ap, \
             patch("app.routers.processing.sync_batch") as sync:
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/clone/apply",
                    json={"batch_name": BATCH, "operations": ops},
                )
        assert resp.json() == sentinel
        ap.assert_called_once_with(
            batch_path=str(_batch_dir(caps)), operations=ops,
        )
        sync.assert_called_once_with(BATCH)


# ---------------------------------------------------------------------------
# Straighten
# ---------------------------------------------------------------------------

class TestStraightenEndpoints:

    def test_analyze_injects_batch_name(self, client, caps):
        tiff = _batch_dir(caps) / "tiff"
        tiff.mkdir()
        (tiff / "mat_top.tiff").write_bytes(b"")
        sentinel = {"skew": 1.5}
        with patch("scripts.processing.straighten_service.analyze",
                   return_value=sentinel) as an:
            resp = client.post(
                "/api/processing/straighten/analyze",
                json={"batch_name": BATCH, "grid_divisions": 24,
                      "direction": "warp"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"skew": 1.5, "batch_name": BATCH}
        an.assert_called_once_with(
            image_path=tiff / "mat_top.tiff", grid_divisions=24,
            direction="warp",
        )

    def test_analyze_no_images_404(self, client, caps):
        resp = client.post(
            "/api/processing/straighten/analyze", json={"batch_name": BATCH}
        )
        assert resp.status_code == 404

    def test_preview_kwargs(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.straighten_service.preview",
                   return_value=sentinel) as pv:
            resp = client.post(
                "/api/processing/straighten/preview",
                json={"batch_name": BATCH, "mode": "skew",
                      "strength": 0.6, "direction": "weft",
                      "grid_divisions": 32, "manual_skew_angle": 2.5},
            )
        assert resp.json() == sentinel
        pv.assert_called_once_with(
            batch_path=_batch_dir(caps), mode="skew", strength=0.6,
            direction="weft", grid_divisions=32, manual_skew_angle=2.5,
        )

    def test_apply_and_sync(self, client, caps):
        sentinel = {"ok": True}
        with patch("scripts.processing.straighten_service.apply",
                   return_value=sentinel) as ap, \
             patch("app.routers.processing.sync_batch") as sync:
            with TestClient(app) as c:
                resp = c.post(
                    "/api/processing/straighten/apply",
                    json={"batch_name": BATCH},
                )
        assert resp.json() == sentinel
        ap.assert_called_once_with(
            batch_path=_batch_dir(caps), mode="auto", strength=1.0,
            direction="both", grid_divisions=20, manual_skew_angle=None,
        )
        sync.assert_called_once_with(BATCH)


# ---------------------------------------------------------------------------
# Pydantic validation (422)
# ---------------------------------------------------------------------------

class TestPydanticValidation:

    def test_calibrate_missing_batch_name_422(self, client, caps):
        resp = client.post("/api/processing/calibrate", json={"profile_name": "P"})
        assert resp.status_code == 422

    def test_crop_apply_bbox_wrong_type_422(self, client, caps):
        resp = client.post(
            "/api/processing/crop/apply",
            json={"batch_name": BATCH, "bbox": "nope"},
        )
        assert resp.status_code == 422

    def test_pbr_selected_images_wrong_type_422(self, client, caps):
        resp = client.post(
            "/api/processing/pbr",
            json={"batch_name": BATCH, "mode": "grayscale",
                  "selected_images": "top"},
        )
        assert resp.status_code == 422

    def test_perspective_points_wrong_type_422(self, client, caps):
        resp = client.post(
            "/api/processing/perspective/preview",
            json={"batch_name": BATCH, "source_points": "not_a_list"},
        )
        assert resp.status_code == 422

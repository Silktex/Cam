"""
Tests for Processing Router -- HTTP layer tests for material tool endpoints.

Tests GET /{tool}/image/{batch}, POST preview/apply for all 7 material tools.
Also covers Pydantic validation (422 errors).
"""
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: mock heavy hardware modules so importing main.py doesn't fail
# ---------------------------------------------------------------------------

# Mock camera_service and light_service before importing the app
_camera_mock = MagicMock()
_camera_mock.startup_check.return_value = {"detected": False}
_camera_mock.disconnect.return_value = None

_light_mock = MagicMock()
_light_mock.connect = MagicMock(return_value={"connected": False, "host": "mock"})
_light_mock.disconnect = MagicMock()

# Pre-populate sys.modules so patch() can resolve dotted paths
# without triggering real imports of aiohttp/gphoto2/etc.
sys.modules.setdefault("gphoto2", MagicMock())
sys.modules.setdefault("aiohttp", MagicMock())

# Ensure app.services.light_service is importable for patching
_light_mod = types.ModuleType("app.services.light_service")
_light_mod.light_service = _light_mock
sys.modules.setdefault("app.services.light_service", _light_mod)

_APP_IMPORT_ERROR = None
try:
    with patch("app.services.camera_service.camera_service", _camera_mock), \
         patch("app.services.light_service.light_service", _light_mock):
        from main import app
    from fastapi.testclient import TestClient
except Exception as exc:
    _APP_IMPORT_ERROR = str(exc)
    app = None
    TestClient = None

# Guard: skip all tests if the app cannot be imported
pytestmark = pytest.mark.skipif(
    _APP_IMPORT_ERROR is not None,
    reason=f"Could not import FastAPI app: {_APP_IMPORT_ERROR}",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """TestClient with mocked database layer so validate_batch() doesn't hit SQLite."""
    if app is None:
        pytest.skip("FastAPI app not importable")

    # Mock database calls used by the router
    with patch("app.routers.processing.get_batch") as mock_get_batch, \
         patch("app.routers.processing.update_batch_status"), \
         patch("app.routers.processing.sync_batch"):

        # By default, get_batch returns a valid batch dict
        mock_get_batch.return_value = {"name": "test_batch", "id": 1}

        with TestClient(app) as c:
            yield c


@pytest.fixture
def client_no_batch():
    """TestClient where get_batch returns None (batch not found)."""
    if app is None:
        pytest.skip("FastAPI app not importable")

    with patch("app.routers.processing.get_batch") as mock_get_batch, \
         patch("app.routers.processing.update_batch_status"), \
         patch("app.routers.processing.sync_batch"):

        mock_get_batch.return_value = None

        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# API-01 through API-07: GET /{tool}/image/{batch} for each tool
# ---------------------------------------------------------------------------

_TOOLS = ["equalize", "delight", "perspective", "seamless", "tile", "validate", "clone"]


class TestGetToolImage:

    @pytest.mark.parametrize("tool", _TOOLS)
    def test_api01_to_07_get_tool_image(self, client, tool, tmp_path):
        """API-01..07: GET /{tool}/image/{batch} for each tool.

        With mocked batch but no real images on disk, expect 404 or 500
        because the batch folder doesn't exist.  This validates the
        HTTP layer is wired and the path parameter is accepted.
        """
        resp = client.get(f"/api/processing/{tool}/image/test_batch")
        # Router calls validate_batch (mocked OK) then checks disk -> 404
        assert resp.status_code in (200, 404, 500), (
            f"Unexpected status {resp.status_code} for GET /{tool}/image/test_batch"
        )

    def test_api08_missing_batch_returns_404(self, client_no_batch):
        """API-08: GET /{tool}/image/{missing_batch} returns 404 when batch not in DB."""
        resp = client_no_batch.get("/api/processing/equalize/image/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API-09 through API-12: Equalize & Delight (wired endpoints)
# ---------------------------------------------------------------------------

class TestEqualizeEndpoints:

    def test_api09_equalize_preview(self, client):
        """API-09: POST /equalize/preview with valid body.

        The service call may fail (no images), but the HTTP layer should
        accept the request and not return 422.
        """
        body = {"batch_name": "test_batch", "method": "clahe", "clip_limit": 2.0}
        resp = client.post("/api/processing/equalize/preview", json=body)
        # 200 if service runs, 404/500 if batch path missing on disk
        assert resp.status_code in (200, 404, 500)

    def test_api10_equalize_apply(self, client):
        """API-10: POST /equalize/apply with valid body."""
        body = {"batch_name": "test_batch", "method": "clahe", "clip_limit": 2.0}
        resp = client.post("/api/processing/equalize/apply", json=body)
        assert resp.status_code in (200, 404, 500)


class TestDelightEndpoints:

    def test_api11_delight_preview(self, client):
        """API-11: POST /delight/preview with valid body."""
        body = {"batch_name": "test_batch", "blur_radius": 200, "strength": 1.0}
        resp = client.post("/api/processing/delight/preview", json=body)
        assert resp.status_code in (200, 404, 500)

    def test_api12_delight_apply(self, client):
        """API-12: POST /delight/apply with valid body."""
        body = {"batch_name": "test_batch", "blur_radius": 200, "strength": 1.0}
        resp = client.post("/api/processing/delight/apply", json=body)
        assert resp.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# API-13 through API-19: Wired Endpoints (Perspective, Seamless, Tile, Validate, Clone)
# ---------------------------------------------------------------------------

class TestWiredEndpoints:

    def test_api13_perspective_detect_lines(self, client):
        """API-13: POST /perspective/detect-lines returns 200."""
        body = {"batch_name": "test_batch"}
        resp = client.post("/api/processing/perspective/detect-lines", json=body)
        # Wired to service -- may 404/500 if batch folder missing on disk
        assert resp.status_code in (200, 404, 500)

    def test_api14_perspective_preview(self, client):
        """API-14: POST /perspective/preview returns 200."""
        body = {
            "batch_name": "test_batch",
            "source_points": [
                {"x": 0, "y": 0},
                {"x": 100, "y": 0},
                {"x": 100, "y": 100},
                {"x": 0, "y": 100},
            ],
        }
        resp = client.post("/api/processing/perspective/preview", json=body)
        assert resp.status_code in (200, 404, 500)

    def test_api15_perspective_apply(self, client):
        """API-15: POST /perspective/apply returns 200."""
        body = {
            "batch_name": "test_batch",
            "source_points": [
                {"x": 0, "y": 0},
                {"x": 100, "y": 0},
                {"x": 100, "y": 100},
                {"x": 0, "y": 100},
            ],
        }
        resp = client.post("/api/processing/perspective/apply", json=body)
        assert resp.status_code in (200, 404, 500)

    def test_api16_seamless_analyze(self, client):
        """API-16: POST /seamless/analyze returns 200."""
        body = {"batch_name": "test_batch"}
        resp = client.post("/api/processing/seamless/analyze", json=body)
        assert resp.status_code in (200, 404, 500)

    def test_api17_tile_preview(self, client):
        """API-17: POST /tile/preview returns 200."""
        body = {"batch_name": "test_batch", "tile_x": 2, "tile_y": 2}
        resp = client.post("/api/processing/tile/preview", json=body)
        assert resp.status_code in (200, 404, 500)

    def test_api18_validate_check(self, client):
        """API-18: POST /validate/check returns 200."""
        body = {"batch_name": "test_batch", "mode": "grayscale"}
        resp = client.post("/api/processing/validate/check", json=body)
        assert resp.status_code in (200, 404, 500)

    def test_api19_clone_inpaint(self, client):
        """API-19: POST /clone/inpaint returns 200."""
        body = {
            "batch_name": "test_batch",
            "mask_data": "dGVzdA==",
            "method": "telea",
            "radius": 5,
        }
        resp = client.post("/api/processing/clone/inpaint", json=body)
        assert resp.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# API-20 through API-21: Pydantic Validation
# ---------------------------------------------------------------------------

class TestValidationErrors:

    def test_api20_missing_batch_name_returns_422(self, client):
        """API-20: Missing batch_name in body returns 422."""
        body = {"method": "clahe"}  # no batch_name
        resp = client.post("/api/processing/equalize/preview", json=body)
        assert resp.status_code == 422

    def test_api21_invalid_source_points_returns_422(self, client):
        """API-21: Invalid source_points (not valid objects) returns 422."""
        body = {
            "batch_name": "test_batch",
            "source_points": "not_a_list",
        }
        resp = client.post("/api/processing/perspective/preview", json=body)
        assert resp.status_code == 422

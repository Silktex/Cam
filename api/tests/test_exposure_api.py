"""
API-level tests for the exposure router (config + status endpoints).

The exposure router imports gphoto2 lazily inside endpoint bodies, so it can be
mounted on a minimal app and tested without a camera or the gphoto2 binding.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.exposure import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/exposure")
    return TestClient(app)


def test_exposure_config_endpoint(client):
    Given = "the exposure router mounted on a minimal app"
    When = "GET /api/exposure/config is called"
    Then = "it returns the feature-gated config with sensible defaults"
    resp = client.get("/api/exposure/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["target_normalized"] == 0.75
    assert body["iso"] == 100


def test_exposure_status_endpoint_without_camera(client):
    Given = "no camera connected"
    When = "GET /api/exposure/status is called"
    Then = "it reports disconnected without crashing"
    resp = client.get("/api/exposure/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


def test_preflight_disabled_returns_400(client):
    Given = "auto exposure is disabled (default)"
    When = "POST /api/exposure/preflight is called"
    Then = "it returns 400 rather than touching the camera"
    resp = client.post("/api/exposure/preflight")
    assert resp.status_code == 400

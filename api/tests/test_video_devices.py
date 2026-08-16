"""
Unit tests for VideoDeviceService, devices router, and liveview source switching
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from main import app
from app.services.video_device_service import VideoDeviceService
from app.services.camera_service import camera_service


@pytest.fixture
def client():
    return TestClient(app)


def test_video_device_service_discovery():
    """Verify VideoDeviceService identifies MacroSilicon HDMI capture card"""
    service = VideoDeviceService()
    
    with patch("glob.glob", return_value=["/sys/class/video4linux/video0"]):
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value="USB3. 0 capture: USB3. 0 captur")))))):
                devices = service.get_devices(refresh=True)
                assert len(devices) == 1
                dev = devices[0]
                assert dev["device_node"] == "/dev/video0"
                assert dev["name"] == "MacroSilicon USB 3.0 HDMI Capture Card"
                assert dev["is_capture_card"] is True
                assert dev["hw_accel"]["encoder"] == "h264_vaapi (AMD Radeon Vega 11)"
                assert dev["stream_endpoints"]["rtsp"] == "rtsp://127.0.0.1:8554/stream"
                assert dev["stream_endpoints"]["whep"] == "/stream/whep"


def test_devices_api_endpoint(client):
    """Verify GET /api/devices/video returns device list"""
    with patch("app.services.video_device_service.video_device_service.get_devices") as mock_get:
        mock_get.return_value = [
            {
                "device_node": "/dev/video0",
                "name": "MacroSilicon USB 3.0 HDMI Capture Card",
                "is_capture_card": True,
                "formats": [{"pixel_format": "MJPG", "description": "Motion-JPEG"}],
            }
        ]
        response = client.get("/api/devices/video")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "MacroSilicon USB 3.0 HDMI Capture Card"


def test_liveview_status_and_source_switching(client):
    """Verify liveview status and switching between HDMI and PTP sources"""
    # Check default status (hdmi)
    response = client.get("/api/liveview/status")
    assert response.status_code == 200
    data = response.json()
    assert data["active_source"] == "hdmi"
    assert data["stream_type"] == "webrtc_h264"
    assert data["whep_url"] == "/stream/whep"
    assert "MacroSilicon" in data["device_name"]

    # Switch to PTP
    response = client.post("/api/liveview/source", json={"source": "ptp"})
    assert response.status_code == 200
    data = response.json()
    assert data["active_source"] == "ptp"
    assert data["stream_type"] == "ptp_direct"

    # Switch back to HDMI
    response = client.post("/api/liveview/source", json={"source": "hdmi"})
    assert response.status_code == 200
    data = response.json()
    assert data["active_source"] == "hdmi"
    assert data["stream_type"] == "webrtc_h264"

    # Invalid source returns 400 or 422 (validation error)
    response = client.post("/api/liveview/source", json={"source": "invalid_src"})
    assert response.status_code in (400, 422)


def test_liveview_capabilities_endpoint(client):
    """Verify GET /api/liveview/capabilities returns capture card and HW encoder info"""
    response = client.get("/api/liveview/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert "capture_card" in data
    assert "hw_encoder" in data
    assert "h264_vaapi" in data["hw_encoder"]["supported_codecs"]

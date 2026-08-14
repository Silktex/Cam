"""
Tests for ExposurePreflightService.

The capture function is a fake that simulates linear RAW response: signal =
brightness * shutter, capped at saturation. No camera or RAW file needed.
"""
import pytest

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.controller import CameraExposureController
from app.services.exposure.preflight import ExposurePreflightService
from app.services.exposure.types import (
    ChannelMetrics,
    ExposureAnalysisResult,
    ExposureSettings,
    ev_correction,
    headroom_ev,
)


class FakeCameraService:
    """In-memory camera service with a coarse shutter ladder."""

    def __init__(self):
        self.config = {
            "shutterspeed": {"name": "shutterspeed", "value": "1/30",
                             "choices": ["1/4000", "1/2000", "1/1000", "1/500",
                                         "1/250", "1/125", "1/60", "1/40", "1/30",
                                         "1/15", "1/8", "0.5", "1", "2", "30"]},
            "iso": {"name": "iso", "value": "100",
                    "choices": ["50", "100", "200", "400", "800", "1600"]},
            "f-number": {"name": "f-number", "value": "8",
                         "choices": ["2.8", "4", "5.6", "8", "11", "16"]},
            "expprogram": {"name": "expprogram", "value": "Manual",
                           "choices": ["Manual", "Aperture Priority"]},
            "autoiso": {"name": "autoiso", "value": 0, "choices": []},
        }

    def get_settings(self):
        return [dict(s) for s in self.config.values()]

    def set_setting(self, name, value):
        if name not in self.config:
            raise Exception(f"unknown setting {name}")
        self.config[name]["value"] = value


def build_controller():
    return CameraExposureController(FakeCameraService(), AutoExposureConfig.defaults())


def make_analysis(measured, shutter, limiting_channel="G1", p95=None):
    clipped = measured >= 0.995
    r = ExposureAnalysisResult()
    r.measured_normalized = min(measured, 1.0)
    r.clipped_fraction = 0.02 if clipped else 0.0
    r.recommended_ev = -1.0 if clipped else ev_correction(min(measured, 1.0), 0.75)
    r.headroom_ev = headroom_ev(max(min(measured, 1.0), 1e-9))
    r.limiting_channel = limiting_channel
    r.metadata_exposure = ExposureSettings(shutter_seconds=shutter)
    p = p95 if p95 is not None else min(measured, 1.0) * 0.8
    r.channel_metrics = {
        "R": ChannelMetrics(p95=p * 0.9),
        "G1": ChannelMetrics(p95=p),
        "B": ChannelMetrics(p95=p * 0.85),
        "G2": ChannelMetrics(p95=p * 0.95),
    }
    return r


def build_capture_fn(brightness_map, controller):
    def capture(light_id):
        shutter = controller.get_current_exposure().shutter_seconds or 0.0
        measured = brightness_map[light_id] * shutter
        return make_analysis(measured, shutter)

    return capture


def build_service(brightness_map):
    controller = build_controller()
    service = ExposurePreflightService(
        controller=controller,
        analyzer=None,
        config=AutoExposureConfig.defaults(),
        activate_light=lambda light_id: None,
        capture=build_capture_fn(brightness_map, controller),
    )
    return service, controller


LIGHTS = [(0, "top"), (1, "front_left"), (2, "left")]


def test_normal_fabric_single_locked_shutter():
    Given = "three lights that all converge near target at a moderate shutter"
    When = "preflight runs"
    Then = "it selects one locked shutter and returns PASS"
    brightness = {0: 22.5, 1: 20.0, 2: 18.0}  # signal per second
    service, controller = build_service(brightness)
    result = service.determine_fixed_sequence_exposure(LIGHTS)
    assert result.status == "PASS"
    assert result.selected_shutter_seconds is not None
    assert result.limiting_light is not None
    # The locked shutter is applied to the camera once.
    assert controller.get_current_exposure().shutter_seconds == pytest.approx(
        result.selected_shutter_seconds, abs=1e-6
    )


def test_bright_light_reduces_exposure():
    Given = "one light that clips at the initial 1/30 shutter"
    When = "preflight runs"
    Then = "it reduces to a shorter safe shutter and passes"
    brightness = {0: 90.0, 1: 22.5, 2: 20.0}  # top light is 4x too bright
    service, _ = build_service(brightness)
    result = service.determine_fixed_sequence_exposure(LIGHTS)
    assert result.status == "PASS"
    assert result.selected_shutter_seconds < 1 / 30
    assert result.predicted_peak < 0.995


def test_dynamic_range_conflict_reported():
    Given = "a bright light forcing a short shutter and a dark light needing a long one"
    When = "preflight runs"
    Then = "it returns FAIL_DYNAMIC_RANGE, not per-light exposure"
    brightness = {0: 90.0, 1: 22.5, 2: 1.5}  # light 2 is far too dark
    service, _ = build_service(brightness)
    result = service.determine_fixed_sequence_exposure(LIGHTS)
    assert result.status == "FAIL_DYNAMIC_RANGE"
    assert any("darkest light" in e for e in result.errors)


def test_iterations_tracked():
    service, _ = build_service({0: 22.5, 1: 20.0, 2: 18.0})
    result = service.determine_fixed_sequence_exposure(LIGHTS)
    assert result.iterations >= len(LIGHTS)

"""
Tests for CameraExposureController using an in-memory fake camera service.

The fake behaves like a real camera: set_setting mutates state and
get_settings reflects it, so read-back verification is meaningful.
"""
import pytest

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.controller import (
    CameraExposureController,
    parse_shutter_seconds,
)
from app.services.exposure.types import ExposureSettings, ShutterOption


class FakeCameraService:
    """In-memory camera service implementing the CameraService config surface."""

    def __init__(self):
        self.config = {
            "shutterspeed": self._menu(
                ["1/4000", "1/2000", "1/1000", "1/500", "1/250", "1/125",
                 "1/60", "1/40", "1/30", "1/15", "1/8", "0.5", "1", "2", "30"],
                "1/30",
            ),
            "iso": self._menu(["50", "100", "200", "400", "800", "1600"], "100"),
            "f-number": self._menu(["2.8", "4", "5.6", "8", "11", "16"], "8"),
            "expprogram": self._menu(["Manual", "Aperture Priority", "Program"], "Manual"),
            "autoiso": {"name": "autoiso", "value": 1, "choices": []},
        }

    @staticmethod
    def _menu(choices, value):
        return {"name": None, "value": value, "choices": choices}

    def get_settings(self):
        out = []
        for name, s in self.config.items():
            item = dict(s)
            item["name"] = name
            out.append(item)
        return out

    def set_setting(self, name, value):
        if name not in self.config:
            raise Exception(f"unknown setting {name}")
        self.config[name]["value"] = value


@pytest.fixture
def controller():
    return CameraExposureController(FakeCameraService(), AutoExposureConfig.defaults())


# --------------------------------------------------------------- parsing


def test_parse_shutter_fraction():
    assert parse_shutter_seconds("1/40") == pytest.approx(0.025)
    assert parse_shutter_seconds("1/4000") == pytest.approx(0.00025)


def test_parse_shutter_seconds():
    assert parse_shutter_seconds("0.5") == pytest.approx(0.5)
    assert parse_shutter_seconds("2") == pytest.approx(2.0)
    assert parse_shutter_seconds("2s") == pytest.approx(2.0)


def test_parse_shutter_bulb_is_none():
    assert parse_shutter_seconds("Bulb") is None
    assert parse_shutter_seconds("B") is None


# --------------------------------------------------------------- enumeration


def test_get_supported_shutter_values(controller):
    values = controller.get_supported_shutter_values()
    assert len(values) > 0
    assert ShutterOption("1/40", pytest.approx(0.025)) in values


def test_get_supported_iso_values(controller):
    assert 100 in controller.get_supported_iso_values()


def test_get_supported_aperture_values(controller):
    assert 8.0 in controller.get_supported_aperture_values()


def test_get_current_exposure(controller):
    exp = controller.get_current_exposure()
    assert exp.iso == 100
    assert exp.aperture == 8.0
    assert exp.shutter_seconds == pytest.approx(1 / 30)
    assert exp.camera_mode == "Manual"


# --------------------------------------------------------------- selection


def test_select_shutter_exact_match(controller):
    opt = controller.select_shutter(0.025, prefer_safe=False)
    assert opt is not None and opt.label == "1/40"


def test_select_shutter_prefers_safe_when_straddling(controller):
    # desired 0.03 lies between 1/30 (0.0333) and 1/40 (0.025).
    safe = controller.select_shutter(0.03, prefer_safe=True)
    assert safe.label == "1/40"  # shorter exposure avoids clipping
    near = controller.select_shutter(0.03, prefer_safe=False)
    assert near.label == "1/30"  # nearest in absolute terms


# --------------------------------------------------------------- set / verify


def test_set_shutter_roundtrip(controller):
    assert controller.set_shutter(ShutterOption("1/40", 0.025))
    assert controller.get_current_exposure().shutter_label == "1/40"


def test_set_shutter_bulb_rejected(controller):
    assert not controller.set_shutter(ShutterOption("Bulb", None))


def test_set_iso_roundtrip(controller):
    assert controller.set_iso(400)
    assert controller.get_current_exposure().iso == 400


def test_set_aperture_roundtrip(controller):
    assert controller.set_aperture(11.0)
    assert controller.get_current_exposure().aperture == pytest.approx(11.0)


def test_verify_exposure_mismatch_false(controller):
    expected = ExposureSettings(iso=100, aperture=8.0, shutter_seconds=0.025)
    assert not controller.verify_exposure(expected)  # actual shutter is 1/30


def test_verify_exposure_match_true(controller):
    controller.set_shutter(ShutterOption("1/40", 0.025))
    expected = ExposureSettings(iso=100, aperture=8.0, shutter_seconds=0.025)
    assert controller.verify_exposure(expected)


# --------------------------------------------------------------- locking


def test_lock_production_settings(controller):
    exposure = ExposureSettings(
        iso=100, aperture=8.0, shutter_seconds=0.025,
        shutter_label="1/40", camera_mode="Manual",
    )
    assert controller.lock_production_settings(exposure)
    current = controller.get_current_exposure()
    assert current.iso == 100
    assert current.aperture == pytest.approx(8.0)
    assert current.shutter_label == "1/40"
    assert controller._camera.config["autoiso"]["value"] == 0


def test_lock_disables_auto_iso(controller):
    controller.lock_production_settings(
        ExposureSettings(iso=100, aperture=8.0, shutter_seconds=0.025, shutter_label="1/40")
    )
    assert controller._camera.config["autoiso"]["value"] == 0

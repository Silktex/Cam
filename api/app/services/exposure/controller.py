"""
CameraExposureController.

Maps desired exposure decisions onto the camera's actually-supported settings
via the existing ``CameraService`` (libgphoto2). It enumerates rather than
hardcodes: shutter/ISO/aperture are discovered from the camera's config tree,
so the controller stays camera-agnostic.

The wrapped camera service is injectable so the controller is unit-testable
with an in-memory fake and no ``gphoto2`` present.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Sequence

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.types import ExposureSettings, ShutterOption

logger = logging.getLogger(__name__)

# Common libgphoto2/Sony config names, tried in order. The controller falls back
# to parsing any widget whose choices look like shutter speeds / ISO / f-stops.
_SHUTTER_KEYS = ("shutterspeed", "shutterspeed2", "shutterspeed_control")
_ISO_KEYS = ("iso", "iso_speed", "isospeed")
_APERTURE_KEYS = ("f-number", "fnumber", "aperture", "fstop")
_AUTO_ISO_KEYS = ("autoiso", "auto_iso")
_MODE_KEYS = ("expprogram", "exposuremode", "mode", "shootingmode")

# "1/40", "1/4000", "0.5", "2", "2s", "30s"
_SHUTTER_FRACTION = re.compile(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$")
_SHUTTER_SECONDS = re.compile(r"^(\d+(?:\.\d+)?)\s*s?$")


def parse_shutter_seconds(label: str) -> Optional[float]:
    """Convert a shutter label to seconds, or None if unparseable/bulb."""
    text = label.strip().lower()
    if text in ("bulb", "b"):
        return None
    if m := _SHUTTER_FRACTION.match(text):
        return float(m.group(1)) / float(m.group(2))
    if m := _SHUTTER_SECONDS.match(text):
        return float(m.group(1))
    return None


def _looks_like_shutter(label: str) -> bool:
    return parse_shutter_seconds(label) is not None


def _looks_like_iso(value: str) -> bool:
    text = value.strip().lower()
    return bool(re.fullmatch(r"\d{1,6}", text)) and " " not in text


def _looks_like_aperture(value: str) -> bool:
    text = value.strip().lower().replace("f/", "").replace("f", "")
    try:
        f = float(text)
    except ValueError:
        return False
    return 0.5 <= f <= 64.0


class CameraExposureController:
    """Control shutter/ISO/aperture through a camera service abstraction."""

    def __init__(self, camera_service=None, config: Optional[AutoExposureConfig] = None):
        self.config = config or AutoExposureConfig.defaults()
        self._camera_service = camera_service

    @property
    def _camera(self):
        if self._camera_service is not None:
            return self._camera_service
        from app.services.camera_service import camera_service

        self._camera_service = camera_service
        return camera_service

    # ------------------------------------------------------------- discovery

    def _settings_map(self) -> dict:
        """Map config name -> setting dict from the camera config tree."""
        settings = self._camera.get_settings() or []
        return {s.get("name"): s for s in settings if s.get("name")}

    def _find_setting(self, keys: Sequence[str], predicate=None):
        settings = self._settings_map()
        for key in keys:
            if key in settings and (
                predicate is None or predicate(settings[key])
            ):
                return settings[key]
        for s in settings.values():
            if predicate is not None and predicate(s):
                return s
        return None

    def get_supported_shutter_values(self) -> List[ShutterOption]:
        setting = self._find_setting(_SHUTTER_KEYS, lambda s: self._choices_look_like_shutter(s))
        if setting is None:
            return []
        return [
            ShutterOption(label=str(c), seconds=parse_shutter_seconds(str(c)))
            for c in setting.get("choices", [])
            if _looks_like_shutter(str(c))
        ]

    @staticmethod
    def _choices_look_like_shutter(setting: dict) -> bool:
        choices = setting.get("choices") or []
        return bool(choices) and all(_looks_like_shutter(str(c)) for c in choices)

    def get_supported_iso_values(self) -> List[int]:
        setting = self._find_setting(_ISO_KEYS, self._choices_look_like_iso)
        if setting is None:
            return []
        return [int(float(str(c))) for c in setting.get("choices", []) if _looks_like_iso(str(c))]

    @staticmethod
    def _choices_look_like_iso(setting: dict) -> bool:
        choices = setting.get("choices") or []
        return bool(choices) and all(_looks_like_iso(str(c)) for c in choices)

    def get_supported_aperture_values(self) -> List[float]:
        setting = self._find_setting(_APERTURE_KEYS, self._choices_look_like_aperture)
        if setting is None:
            return []
        return [float(str(c).replace("f/", "").replace("f", "")) for c in setting.get("choices", []) if _looks_like_aperture(str(c))]

    @staticmethod
    def _choices_look_like_aperture(setting: dict) -> bool:
        choices = setting.get("choices") or []
        return bool(choices) and all(_looks_like_aperture(str(c)) for c in choices)

    # ---------------------------------------------------------------- current

    def get_current_exposure(self) -> ExposureSettings:
        settings = self._settings_map()
        return ExposureSettings(
            iso=self._read_int(settings, _ISO_KEYS),
            aperture=self._read_float(settings, _APERTURE_KEYS),
            shutter_label=self._read_str(settings, _SHUTTER_KEYS),
            shutter_seconds=self._read_shutter_seconds(settings),
            camera_mode=self._read_str(settings, _MODE_KEYS),
        )

    def _read_str(self, settings: dict, keys: Sequence[str]) -> Optional[str]:
        for key in keys:
            if key in settings:
                v = settings[key].get("value")
                if v is not None:
                    return str(v)
        return None

    def _read_int(self, settings: dict, keys: Sequence[str]) -> Optional[int]:
        for key in keys:
            if key in settings:
                v = settings[key].get("value")
                if v is not None:
                    try:
                        return int(float(str(v)))
                    except (TypeError, ValueError):
                        return None
        return None

    def _read_float(self, settings: dict, keys: Sequence[str]) -> Optional[float]:
        for key in keys:
            if key in settings:
                v = settings[key].get("value")
                if v is not None:
                    try:
                        return float(str(v).replace("f/", "").replace("f", ""))
                    except (TypeError, ValueError):
                        return None
        return None

    def _read_shutter_seconds(self, settings: dict) -> Optional[float]:
        label = self._read_str(settings, _SHUTTER_KEYS)
        return parse_shutter_seconds(label) if label else None

    # ------------------------------------------------------------------ set

    def _set_config(self, keys: Sequence[str], value) -> Optional[str]:
        settings = self._settings_map()
        name = next((k for k in keys if k in settings), None)
        if name is None:
            return None
        try:
            self._camera.set_setting(name, value)
        except Exception as e:
            logger.warning(f"Camera rejected setting {name}={value!r}: {e}")
            return None
        return name

    def set_shutter(self, option: ShutterOption) -> bool:
        if option.seconds is None:
            return False
        name = self._set_config(_SHUTTER_KEYS, option.label)
        if name is None:
            return False
        return self._verify_value(name, option.label)

    def set_iso(self, iso: int) -> bool:
        name = self._set_config(_ISO_KEYS, str(iso))
        if name is None:
            return False
        return self._verify_value(name, str(iso))

    def set_aperture(self, aperture: float) -> bool:
        name = self._set_config(_APERTURE_KEYS, f"{aperture:g}")
        if name is None:
            return False
        return self._verify_value(name, f"{aperture:g}")

    def _verify_value(self, name: str, expected: str) -> bool:
        settings = self._settings_map()
        actual = settings.get(name, {}).get("value")
        return str(actual).strip() == str(expected).strip()

    # -------------------------------------------------------------- selection

    def select_shutter(self, desired_seconds: float, prefer_safe: bool = True) -> Optional[ShutterOption]:
        """Pick the nearest supported shutter to ``desired_seconds``.

        When two options straddle the target, ``prefer_safe=True`` returns the
        shorter exposure (smaller seconds) to avoid increased clipping risk.
        """
        options = self.get_supported_shutter_values()
        usable = [o for o in options if o.seconds is not None]
        if not usable:
            return None
        nearest = min(usable, key=lambda o: abs(o.seconds - desired_seconds))
        if prefer_safe:
            safe = min(
                (o for o in usable if o.seconds <= desired_seconds),
                key=lambda o: desired_seconds - o.seconds,
                default=None,
            )
            if safe is not None and safe.seconds >= nearest.seconds * 0.5:
                return safe
        return nearest

    # -------------------------------------------------------------- locking

    def verify_exposure(self, expected: ExposureSettings) -> bool:
        current = self.get_current_exposure()
        if expected.iso is not None and current.iso != expected.iso:
            return False
        if expected.aperture is not None and current.aperture is not None:
            if abs(current.aperture - expected.aperture) > 0.1:
                return False
        if expected.shutter_seconds is not None and current.shutter_seconds is not None:
            if abs(current.shutter_seconds - expected.shutter_seconds) > expected.shutter_seconds * 0.05 + 1e-6:
                return False
        return True

    def lock_production_settings(self, exposure: ExposureSettings) -> bool:
        """Set Manual mode, ISO, aperture, shutter, and disable auto ISO."""
        for key in _AUTO_ISO_KEYS:
            settings = self._settings_map()
            if key in settings:
                try:
                    self._camera.set_setting(key, 0)
                except Exception as e:
                    # Best-effort: not all bodies expose an auto-ISO toggle.
                    logger.debug(f"Failed to disable auto-ISO via {key!r}: {e}")

        ok = True
        if exposure.camera_mode is not None:
            ok &= bool(self._set_config(_MODE_KEYS, exposure.camera_mode))
        if exposure.iso is not None:
            ok &= self.set_iso(exposure.iso)
        if exposure.aperture is not None:
            ok &= self.set_aperture(exposure.aperture)
        if exposure.shutter_label is not None and exposure.shutter_seconds is not None:
            ok &= self.set_shutter(
                ShutterOption(exposure.shutter_label, exposure.shutter_seconds)
            )
        return ok and self.verify_exposure(exposure)

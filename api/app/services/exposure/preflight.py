"""
Exposure preflight: determine ONE safe fixed exposure for a full
photometric-stereo sequence.

Default strategy ``all_lights_safe_exposure``: for each directional LED, find a
non-clipping shutter, then pick the shortest (safest) one and verify it across
all lights at that locked shutter. Produces a single locked exposure — never
per-light auto-exposure (PRD §4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.raw_analyzer import RawExposureAnalyzer
from app.services.exposure.types import ExposureAnalysisResult

# A directional light: (id, human-readable name).
LightRef = Tuple[int, str]

# Injected seam: activate a single light (others off) before capture.
LightActivator = Callable[[int], None]
# Injected seam: capture a RAW at the CURRENT camera shutter and analyze it.
CaptureFn = Callable[[int], ExposureAnalysisResult]


@dataclass
class PreflightResult:
    status: str = "PASS"
    selected_shutter_seconds: Optional[float] = None
    selected_shutter_label: Optional[str] = None
    iso: Optional[int] = None
    aperture: Optional[float] = None
    limiting_light: Optional[str] = None
    limiting_channel: Optional[str] = None
    predicted_peak: Optional[float] = None
    headroom_ev: Optional[float] = None
    iterations: int = 0
    light_results: Dict[str, ExposureAnalysisResult] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _min_channel_p95(analysis: ExposureAnalysisResult) -> float:
    """Dimmest channel's P95 — the signal bottleneck for underexposure."""
    if not analysis.channel_metrics:
        return 0.0
    return min(m.p95 for m in analysis.channel_metrics.values())


class ExposurePreflightService:
    """Find a single safe shutter for all lights via injected seams."""

    def __init__(
        self,
        controller,
        analyzer: RawExposureAnalyzer,
        config: Optional[AutoExposureConfig] = None,
        activate_light: Optional[LightActivator] = None,
        capture: Optional[CaptureFn] = None,
    ):
        self.controller = controller
        self.analyzer = analyzer
        self.config = config or AutoExposureConfig.defaults()
        self.activate_light = activate_light
        self.capture = capture

    def determine_fixed_sequence_exposure(
        self, lights: Sequence[LightRef]
    ) -> PreflightResult:
        if self.capture is None:
            raise ValueError("preflight requires an injected capture function")

        result = PreflightResult()
        current = self.controller.get_current_exposure()
        result.iso = current.iso
        result.aperture = current.aperture

        safe_shutters: Dict[str, float] = {}
        for light_id, light_name in lights:
            if self.activate_light is not None:
                self.activate_light(light_id)
            shutter = self._preflight_light(light_id, result)
            if shutter is None:
                result.status = "FAIL_NON_CONVERGENCE"
                result.errors.append(f"light {light_name} did not converge")
                return result
            safe_shutters[light_name] = shutter

        selected_seconds = min(safe_shutters.values())
        option = self.controller.select_shutter(selected_seconds, prefer_safe=True)
        if option is None or option.seconds is None:
            result.status = "FAIL_SHUTTER_UNAVAILABLE"
            result.errors.append(f"no supported shutter for {selected_seconds}s")
            return result
        self.controller.set_shutter(option)
        result.selected_shutter_seconds = option.seconds
        result.selected_shutter_label = option.label

        # Verification pass at the locked shutter (PRD §29: always verify).
        result.light_results = {}
        for light_id, light_name in lights:
            if self.activate_light is not None:
                self.activate_light(light_id)
            analysis = self.capture(light_id)
            result.light_results[light_name] = analysis
            if analysis.clipped_fraction > self.config.max_hard_clip_fraction:
                result.status = "FAIL_CLIPPING"
                result.errors.append(f"light {light_name} clips at locked shutter")
                return result

        limiting_light = max(
            result.light_results,
            key=lambda k: result.light_results[k].measured_normalized,
        )
        limiting = result.light_results[limiting_light]
        result.limiting_light = limiting_light
        result.limiting_channel = limiting.limiting_channel
        result.predicted_peak = limiting.measured_normalized
        result.headroom_ev = limiting.headroom_ev

        # Dynamic-range check on the darkest light (PRD G10).
        darkest = min(
            result.light_results,
            key=lambda k: _min_channel_p95(result.light_results[k]),
        )
        darkest_p95 = _min_channel_p95(result.light_results[darkest])
        if darkest_p95 < self.config.minimum_p95_normalized:
            result.status = "FAIL_DYNAMIC_RANGE"
            result.errors.append(
                f"darkest light {darkest} P95={darkest_p95:.4f} below "
                f"minimum {self.config.minimum_p95_normalized}; "
                f"brightest light {limiting_light} forces {result.selected_shutter_label}"
            )
            return result

        result.status = "PASS"
        return result

    # ------------------------------------------------------------- internals

    def _preflight_light(self, light_id: int, result: PreflightResult) -> Optional[float]:
        # Reset to a known starting shutter for each light.
        start = self.config.initial_shutter_seconds
        if start is None:
            start = self.controller.get_current_exposure().shutter_seconds or 0.0
        start_option = self.controller.select_shutter(start, prefer_safe=True)
        if start_option is not None and start_option.seconds is not None:
            self.controller.set_shutter(start_option)
        shutter = start_option.seconds if start_option else start
        last: Optional[ExposureAnalysisResult] = None

        for _ in range(self.config.max_preflight_iterations):
            result.iterations += 1
            analysis = self.capture(light_id)
            last = analysis

            if analysis.clipped_fraction > self.config.max_hard_clip_fraction:
                # Clipped: the true signal is unknown, so reduce conservatively
                # by a full stop rather than inferring from the clipped value.
                correction = -1.0
            else:
                correction = analysis.recommended_ev

            correction = max(
                -self.config.max_adjustment_per_iteration_ev,
                min(self.config.max_adjustment_per_iteration_ev, correction),
            )
            if abs(correction) <= self.config.convergence_tolerance_ev:
                return shutter

            new_shutter = shutter * (2.0 ** correction)
            option = self.controller.select_shutter(new_shutter, prefer_safe=True)
            if option is None or option.seconds is None:
                return None
            self.controller.set_shutter(option)
            shutter = option.seconds

        # Ran out of iterations; only a problem if still clipping.
        if last is not None and last.clipped_fraction > self.config.max_hard_clip_fraction:
            return None
        return shutter

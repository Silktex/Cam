"""
ExposureService facade.

Wires the pure exposure domain (analyzer, controller, preflight, QA) to the
real camera and light services. Imports of gphoto2/rawpy happen lazily inside
methods so this module imports cleanly in hardware-free environments.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.controller import CameraExposureController
from app.services.exposure.preflight import ExposurePreflightService, PreflightResult
from app.services.exposure.qa import ExposureQaService, QaResult
from app.services.exposure.raw_analyzer import RawExposureAnalyzer
from app.services.exposure.types import ExposureAnalysisResult, ExposureSettings

logger = logging.getLogger(__name__)

# (light id, name) for the 9-light rig: top + sides 1-8.
RIG_LIGHTS = [(0, "top")] + [(i, f"side_{i}") for i in range(1, 9)]


@dataclass
class ExposureServices:
    config: AutoExposureConfig
    analyzer: RawExposureAnalyzer
    controller: CameraExposureController
    preflight: ExposurePreflightService
    qa: ExposureQaService


def build_services(config: AutoExposureConfig) -> ExposureServices:
    """Assemble the exposure domain with the real camera/light seams."""
    controller = CameraExposureController(config=config)
    analyzer = RawExposureAnalyzer(config)

    from app.services.camera_service import camera_service
    from app.services.light_service import light_service

    def activate_light(light_id: int) -> None:
        # ESP32 control is async; run in a fresh loop via a blocking helper.
        import asyncio

        async def _activate():
            await light_service.set_all_lights(on=False)
            await light_service.set_light(light_id, on=True, brightness=100)

        asyncio.get_event_loop().run_until_complete(_activate())

    def capture(light_id: int) -> ExposureAnalysisResult:
        result = camera_service.capture_image(
            folder="_preflight", prefix="preflight", suffix=f"light_{light_id}",
            skip_post_process=True,
        )
        if not result.get("success"):
            return _failed_analysis(result.get("error", "capture failed"))
        raw_path = Path(result["filepath"])
        exposure = controller.get_current_exposure()
        return analyzer.analyze_file(raw_path, metadata_exposure=exposure)

    preflight = ExposurePreflightService(
        controller=controller,
        analyzer=analyzer,
        config=config,
        activate_light=activate_light,
        capture=capture,
    )
    qa = ExposureQaService(config)
    return ExposureServices(config, analyzer, controller, preflight, qa)


def _failed_analysis(message: str) -> ExposureAnalysisResult:
    result = ExposureAnalysisResult(status="CAPTURE_FAILED")
    result.errors.append(message)
    return result


def run_preflight(
    services: ExposureServices, lights: Optional[List] = None
) -> PreflightResult:
    lights = lights or RIG_LIGHTS
    return services.preflight.determine_fixed_sequence_exposure(lights)


def qa_frame(
    services: ExposureServices,
    analysis: ExposureAnalysisResult,
    locked: ExposureSettings,
    retake_count: int = 0,
) -> QaResult:
    return services.qa.evaluate(analysis, locked, retake_count)

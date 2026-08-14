"""
Per-capture exposure QA.

Validates every captured RAW frame against the locked sequence exposure and
configured quality limits, producing PASS / WARNING / RETAKE / FAIL. Drift
detection flags any unexpected change in ISO/aperture/shutter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.types import (
    ExposureAnalysisResult,
    ExposureSettings,
    QaStatus,
)


@dataclass
class QaResult:
    status: QaStatus = QaStatus.PASS
    reason: str = ""
    warnings: List[str] = field(default_factory=list)


class ExposureQaService:
    """Classify a frame's exposure analysis against the locked sequence exposure."""

    def __init__(self, config: Optional[AutoExposureConfig] = None):
        self.config = config or AutoExposureConfig.defaults()

    def evaluate(
        self,
        analysis: ExposureAnalysisResult,
        locked: ExposureSettings,
        retake_count: int = 0,
    ) -> QaResult:
        if analysis.status != "OK":
            return QaResult(QaStatus.FAIL, f"RAW analysis failed: {analysis.status}")

        drift = self._drift_reason(analysis, locked)
        if drift:
            return QaResult(QaStatus.FAIL, drift)

        if analysis.clipped_fraction > self.config.max_hard_clip_fraction:
            return QaResult(
                QaStatus.FAIL,
                f"hard clipping {analysis.clipped_fraction:.6f} exceeds "
                f"limit {self.config.max_hard_clip_fraction}",
            )

        if analysis.underexposed_fraction > 0.5:
            return QaResult(
                QaStatus.FAIL,
                f"underexposed fraction {analysis.underexposed_fraction:.3f} too high",
            )

        # A clipped-but-below-failure frame is retakeable (scene/light anomaly).
        if analysis.clipped_fraction > 0.0:
            if retake_count < self.config.retake_limit:
                return QaResult(
                    QaStatus.RETAKE,
                    f"clipping {analysis.clipped_fraction:.6f} detected; retake {retake_count + 1}/{self.config.retake_limit}",
                )
            return QaResult(QaStatus.FAIL, "clipping persists after retake limit")

        if analysis.near_clipped_fraction > self.config.max_near_clip_fraction:
            return QaResult(
                QaStatus.WARNING,
                f"near-clipping {analysis.near_clipped_fraction:.6f} above limit",
            )

        measured = analysis.measured_normalized
        if measured < self.config.acceptable_low or measured > self.config.acceptable_high:
            return QaResult(
                QaStatus.WARNING,
                f"limiting P99.9 {measured:.3f} outside [{self.config.acceptable_low}, "
                f"{self.config.acceptable_high}]",
            )

        return QaResult(QaStatus.PASS)

    def _drift_reason(
        self, analysis: ExposureAnalysisResult, locked: ExposureSettings
    ) -> Optional[str]:
        actual = analysis.metadata_exposure
        if actual is None:
            return None
        if (
            locked.iso is not None
            and actual.iso is not None
            and actual.iso != locked.iso
        ):
            return f"exposure drift: ISO {actual.iso} != locked {locked.iso}"
        if (
            locked.aperture is not None
            and actual.aperture is not None
            and abs(actual.aperture - locked.aperture) > 0.1
        ):
            return f"exposure drift: aperture {actual.aperture} != locked {locked.aperture}"
        if (
            locked.shutter_seconds is not None
            and actual.shutter_seconds is not None
            and abs(actual.shutter_seconds - locked.shutter_seconds)
            > locked.shutter_seconds * 0.05 + 1e-6
        ):
            return (
                f"exposure drift: shutter {actual.shutter_seconds}s != locked "
                f"{locked.shutter_seconds}s"
            )
        return None

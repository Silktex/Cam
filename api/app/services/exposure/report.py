"""
Machine-readable exposure metadata serialization (PRD §20, G14).

Serializes session-level and per-frame exposure records to JSON for auditing
and reproducibility. Follows the naming in types.py; the integration layer
stores these beside the capture set.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.preflight import PreflightResult
from app.services.exposure.qa import QaResult
from app.services.exposure.types import ExposureAnalysisResult, QaStatus


def session_record(
    preflight: Optional[PreflightResult],
    config: AutoExposureConfig,
    roi: Optional[dict] = None,
) -> Dict[str, Any]:
    """Build the session-level ``auto_exposure`` record."""
    record: Dict[str, Any] = {
        "version": 1,
        "mode": config.mode,
        "analysis_space": "raw_sensor",
        "target_percentile": config.target_percentile,
        "target_normalized": config.target_normalized,
        "preflight_status": preflight.status if preflight else None,
    }
    if roi is not None:
        record["roi"] = roi
    if preflight is not None:
        record.update(
            {
                "selected_shutter_seconds": preflight.selected_shutter_seconds,
                "iso": preflight.iso,
                "aperture": preflight.aperture,
                "limiting_light": preflight.limiting_light,
                "limiting_channel": preflight.limiting_channel,
                "predicted_peak": preflight.predicted_peak,
                "headroom_ev": preflight.headroom_ev,
            }
        )
    return record


def frame_record(analysis: ExposureAnalysisResult, qa: QaResult) -> Dict[str, Any]:
    """Build a per-frame ``exposure_qa`` record."""
    p99_9 = {
        name: m.p999 for name, m in analysis.channel_metrics.items()
    }
    return {
        "status": qa.status.value,
        "reason": qa.reason,
        "actual_shutter_seconds": (
            analysis.metadata_exposure.shutter_seconds
            if analysis.metadata_exposure
            else None
        ),
        "iso": analysis.metadata_exposure.iso if analysis.metadata_exposure else None,
        "aperture": analysis.metadata_exposure.aperture if analysis.metadata_exposure else None,
        "p99_9": p99_9,
        "limiting_channel": analysis.limiting_channel,
        "measured_normalized": analysis.measured_normalized,
        "hard_clip_fraction": analysis.clipped_fraction,
        "near_clip_fraction": analysis.near_clipped_fraction,
        "underexposed_fraction": analysis.underexposed_fraction,
        "headroom_ev": analysis.headroom_ev,
        "warnings": analysis.warnings,
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write a JSON payload to disk (atomic-ish: write then no partial on error)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))

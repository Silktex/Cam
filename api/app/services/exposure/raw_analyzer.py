"""
RAW sensor analyzer for exposure decisions.

Reads the RAW **mosaic** (linear sensor values) — never the embedded JPEG or a
demosaiced RGB image — and produces per-channel statistics suitable for safe,
repeatable exposure control in a photometric-stereo rig.

Rationale (PRD §7): exposure decisions must be made from linear sensor values
with per-channel black/white levels applied. No gamma, no tone curve, no
white-balance gain, and no auto-brightness may influence clipping analysis.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.types import (
    ChannelMetrics,
    ExposureAnalysisResult,
    ExposureSettings,
    Roi,
    RoiType,
    ev_correction,
    headroom_ev,
)

logger = logging.getLogger(__name__)

# CFA color index -> channel name (rawpy ``raw_colors`` convention).
# 0 = R, 1 = G1 (green on the red row), 2 = B, 3 = G2 (green on the blue row).
CHANNEL_INDEX_TO_NAME: Tuple[str, str, str, str] = ("R", "G1", "B", "G2")
CHANNEL_NAMES: Tuple[str, ...] = ("R", "G1", "G2", "B")
_P99_99_MIN_PIXELS = 10_000


class RawExposureAnalyzer:
    """Analyze a RAW Bayer mosaic and return an ExposureAnalysisResult."""

    def __init__(self, config: AutoExposureConfig):
        self.config = config

    # ------------------------------------------------------------------ public

    def analyze_mosaic(
        self,
        mosaic: np.ndarray,
        cfa: np.ndarray,
        black_levels: Union[float, Sequence[float]],
        white_levels: Union[float, Sequence[float]],
        roi: Optional[Roi] = None,
        metadata_exposure: Optional[ExposureSettings] = None,
    ) -> ExposureAnalysisResult:
        """Analyze a RAW Bayer mosaic.

        Args:
            mosaic: 2D array (H, W) of linear RAW sensor values.
            cfa: 2D integer array (H, W) of CFA color indices, matching the
                rawpy ``raw_colors`` convention: 0=R, 1=G1, 2=B, 3=G2.
            black_levels: scalar or per-channel (length 4) black level.
            white_levels: scalar or per-channel (length 4) saturation level.
            roi: optional analysis region.
            metadata_exposure: exposure settings recorded alongside the RAW.

        Raises ValueError for malformed input (shape mismatch, non-Bayer CFA,
        invalid black/white levels). Soft issues are reported via warnings.
        """
        if mosaic.ndim != 2:
            raise ValueError(f"mosaic must be 2D, got shape {mosaic.shape}")
        if cfa.shape != mosaic.shape:
            raise ValueError(
                f"cfa shape {cfa.shape} does not match mosaic shape {mosaic.shape}"
            )
        if cfa.size == 0:
            raise ValueError("mosaic is empty")

        # Non-Bayer layouts (e.g. X-Trans) use color indices beyond 0..3.
        if np.any((cfa < 0) | (cfa > 3)):
            raise ValueError(
                "non-Bayer CFA layout detected; only 2x2 Bayer (R/G1/B/G2) is supported"
            )

        black = self._as_channel_levels(black_levels, "black")
        white = self._as_channel_levels(white_levels, "white")
        if np.any(white <= black):
            raise ValueError(
                f"white levels must exceed black levels; black={black}, white={white}"
            )

        mosaic_roi, cfa_roi, applied_roi = self._apply_roi(mosaic, cfa, roi)
        h, w = mosaic_roi.shape
        warnings: List[str] = []

        channel_metrics = {}
        for idx, name in enumerate(CHANNEL_INDEX_TO_NAME):
            mask = cfa_roi == idx
            if not np.any(mask):
                continue  # channel absent from this CFA region
            values = mosaic_roi[mask].astype(np.float64)
            normalized = (values - black[idx]) / (white[idx] - black[idx])
            channel_metrics[name] = self._channel_metrics(normalized, warnings, name)

        if not channel_metrics:
            raise ValueError("no CFA pixels found for any channel")

        # The limiting channel is the one nearest saturation (highest P99.9).
        limiting_channel = max(
            channel_metrics, key=lambda k: channel_metrics[k].p999
        )
        measured = channel_metrics[limiting_channel].p999

        if measured <= 0.0:
            recommended_ev = float(self.config.max_adjustment_per_iteration_ev)
            headroom = float("inf")
            warnings.append(
                f"limiting channel {limiting_channel} P99.9 at/below black; "
                "exposure correction clamped to +max per-iteration"
            )
        else:
            recommended_ev = ev_correction(measured, self.config.target_normalized)
            headroom = headroom_ev(measured)

        clipped_count = sum(m.clipped_count for m in channel_metrics.values())
        total_pixels = int(h * w)
        clipped_fraction = clipped_count / total_pixels if total_pixels else 0.0
        near_clipped_count = sum(
            int(m.near_clipped_fraction * total_pixels) for m in channel_metrics.values()
        )
        near_clipped_fraction = (
            sum(m.near_clipped_fraction for m in channel_metrics.values())
        )
        underexposed_fraction = self._underexposed_fraction(
            mosaic_roi, cfa_roi, black, white
        )

        return ExposureAnalysisResult(
            status="OK",
            raw_width=w,
            raw_height=h,
            roi=applied_roi,
            black_levels=list(black),
            white_levels=list(white),
            channel_metrics=channel_metrics,
            limiting_channel=limiting_channel,
            control_percentile=self.config.target_percentile,
            measured_normalized=float(measured),
            target_normalized=self.config.target_normalized,
            recommended_ev=recommended_ev,
            headroom_ev=headroom,
            clipped_count=clipped_count,
            clipped_fraction=clipped_fraction,
            near_clipped_count=near_clipped_count,
            near_clipped_fraction=near_clipped_fraction,
            underexposed_fraction=underexposed_fraction,
            metadata_exposure=metadata_exposure,
            warnings=warnings,
        )

    def analyze_file(
        self,
        raw_path: Union[str, Path],
        roi: Optional[Roi] = None,
        metadata_exposure: Optional[ExposureSettings] = None,
    ) -> ExposureAnalysisResult:
        """Analyze a RAW file on disk via rawpy (lazy import).

        This is the production entry point. It is not exercised by the unit
        tests here (rawpy is only installed inside the Docker image); the
        numeric logic lives in :meth:`analyze_mosaic` and is fully unit-tested.
        """
        try:
            import rawpy
        except ImportError as exc:  # pragma: no cover - Docker-only path
            return self._error_result(
                "RAW_DECODE_IMPORT_FAILED",
                "rawpy is not installed; run inside the Docker image",
                raw_path,
            )

        try:
            with rawpy.imread(str(raw_path)) as raw:
                mosaic = raw.raw_image_visible
                cfa = raw.raw_colors_visible
                black = list(raw.black_level_per_channel) or [float(raw.black_level)] * 4
                white_per_channel = raw.camera_white_level_per_channel
                white: Union[float, List[float]] = (
                    list(white_per_channel)
                    if white_per_channel and len(white_per_channel) >= 4
                    else float(raw.white_level)
                )
                return self.analyze_mosaic(
                    mosaic, cfa, black, white, roi, metadata_exposure
                )
        except Exception as exc:
            return self._error_result("RAW_DECODE_FAILED", str(exc), raw_path)

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _as_channel_levels(
        levels: Union[float, Sequence[float]], name: str
    ) -> np.ndarray:
        arr = np.asarray(levels, dtype=np.float64)
        if arr.ndim == 0:
            arr = np.full(4, float(arr))
        if arr.shape != (4,):
            raise ValueError(f"{name} levels must be scalar or length-4, got {arr.shape}")
        return arr

    def _apply_roi(
        self, mosaic: np.ndarray, cfa: np.ndarray, roi: Optional[Roi]
    ) -> Tuple[np.ndarray, np.ndarray, Optional[Roi]]:
        h, w = mosaic.shape
        if roi is None or roi.type == RoiType.FULL_FRAME:
            return mosaic, cfa, None

        if roi.type == RoiType.CENTER_CROP:
            x1, y1 = w // 4, h // 4
            x2, y2 = w - w // 4, h - h // 4
            applied = Roi(RoiType.CENTER_CROP, x1, y1, x2 - x1, y2 - y1)
        elif roi.type in (RoiType.CONFIGURED_ROI, RoiType.CAPTURE_AREA_MASK):
            x1 = max(0, roi.x)
            y1 = max(0, roi.y)
            x2 = min(w, roi.x + roi.width) if roi.width else w
            y2 = min(h, roi.y + roi.height) if roi.height else h
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f"invalid ROI {roi} for {w}x{h} mosaic")
            applied = Roi(roi.type, x1, y1, x2 - x1, y2 - y1)
        else:  # pragma: no cover - exhaustive RoiType
            raise ValueError(f"unsupported ROI type: {roi.type}")

        return mosaic[y1:y2, x1:x2], cfa[y1:y2, x1:x2], applied

    def _channel_metrics(
        self, normalized: np.ndarray, warnings: List[str], name: str
    ) -> ChannelMetrics:
        n = normalized.size
        percentiles = np.percentile(
            normalized, [50.0, 90.0, 95.0, 99.0, 99.9]
        )
        p9999 = None
        if n >= _P99_99_MIN_PIXELS:
            p9999 = float(np.percentile(normalized, 99.99))
        else:
            warnings.append(
                f"channel {name} has {n} pixels (< {_P99_99_MIN_PIXELS}); P99.99 unavailable"
            )

        hard = normalized >= self.config.hard_clip_threshold
        near = (normalized >= self.config.near_clip_threshold) & ~hard
        clipped_count = int(np.count_nonzero(hard))

        return ChannelMetrics(
            min_norm=float(np.min(normalized)),
            p50=float(percentiles[0]),
            p90=float(percentiles[1]),
            p95=float(percentiles[2]),
            p99=float(percentiles[3]),
            p999=float(percentiles[4]),
            p9999=p9999,
            max_norm=float(np.max(normalized)),
            clipped_count=clipped_count,
            clipped_fraction=clipped_count / n,
            near_clipped_fraction=float(np.count_nonzero(near)) / n,
        )

    def _underexposed_fraction(
        self,
        mosaic: np.ndarray,
        cfa: np.ndarray,
        black: np.ndarray,
        white: np.ndarray,
    ) -> float:
        """Fraction of ROI pixels at/below the configured dark threshold."""
        normalized = np.zeros_like(mosaic, dtype=np.float64)
        for idx in range(4):
            mask = cfa == idx
            if not np.any(mask):
                continue
            normalized[mask] = (mosaic[mask].astype(np.float64) - black[idx]) / (
                white[idx] - black[idx]
            )
        return float(
            np.count_nonzero(normalized <= self.config.minimum_median_above_black)
            / normalized.size
        )

    @staticmethod
    def _error_result(code: str, message: str, raw_path: Union[str, Path]) -> ExposureAnalysisResult:
        result = ExposureAnalysisResult(status=code)
        result.errors.append(f"{raw_path}: {message}")
        return result

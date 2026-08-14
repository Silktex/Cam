"""
Tests for the RAW exposure analyzer and exposure domain types.

Pure numpy — no rawpy/gphoto2 required. Synthetic Bayer mosaics exercise the
normalization, percentile, clipping, EV, headroom, and ROI logic.
"""
import math

import numpy as np
import pytest

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.raw_analyzer import RawExposureAnalyzer
from app.services.exposure.types import (
    ExposureSettings,
    Roi,
    RoiType,
    ev_correction,
    headroom_ev,
)


def make_rggb_cfa(h: int, w: int) -> np.ndarray:
    """Build an RGGB CFA index array: 0=R, 1=G1, 2=B, 3=G2."""
    cfa = np.empty((h, w), dtype=np.int64)
    cfa[0::2, 0::2] = 0  # R
    cfa[0::2, 1::2] = 1  # G1 (green on red row)
    cfa[1::2, 0::2] = 3  # G2 (green on blue row)
    cfa[1::2, 1::2] = 2  # B
    return cfa


def make_uniform_mosaic(h: int, w: int, raw_value: int) -> np.ndarray:
    return np.full((h, w), raw_value, dtype=np.uint16)


def make_gradient_mosaic(h: int, w: int, low: int, high: int) -> np.ndarray:
    """Horizontal gradient mosaic (per-channel uniform along columns)."""
    gradient = np.linspace(low, high, w, dtype=np.uint16)
    return np.tile(gradient, (h, 1))


@pytest.fixture
def analyzer():
    return RawExposureAnalyzer(AutoExposureConfig.defaults())


# ---------------------------------------------------------------- EV math


def test_ev_correction_half_to_target_is_plus_one():
    Given = "a measured signal of 0.375 and target 0.75"
    When = "ev_correction is called"
    Then = "the correction is +1 EV"
    assert ev_correction(0.375, 0.75) == pytest.approx(1.0)


def test_ev_correction_at_target_is_zero():
    assert ev_correction(0.75, 0.75) == pytest.approx(0.0)


def test_ev_correction_overexposed_is_negative():
    assert ev_correction(0.90, 0.75) == pytest.approx(math.log2(0.75 / 0.90))


def test_ev_correction_rejects_nonpositive_current():
    with pytest.raises(ValueError):
        ev_correction(0.0, 0.75)


def test_headroom_ev_examples():
    assert headroom_ev(0.5) == pytest.approx(1.0)
    assert headroom_ev(0.75) == pytest.approx(0.415, abs=1e-3)
    assert headroom_ev(0.9) == pytest.approx(0.152, abs=1e-3)


# ---------------------------------------------------------------- normalization


def test_normalization_formula(analyzer):
    Given = "black=512, white=16383, raw=8447 (PRD §35 example)"
    When = "a uniform mosaic at that raw value is analyzed"
    Then = "the normalized value is (8447-512)/(16383-512)"
    mosaic = make_uniform_mosaic(64, 64, 8447)
    cfa = make_rggb_cfa(64, 64)
    result = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383)
    expected = (8447 - 512) / (16383 - 512)
    for m in result.channel_metrics.values():
        assert m.p50 == pytest.approx(expected, abs=1e-9)
    assert result.status == "OK"


def test_per_channel_black_white_levels(analyzer):
    Given = "distinct per-channel black and white levels"
    When = "channels carry different raw values"
    Then = "each channel normalizes with its own levels"
    h = w = 32
    mosaic = np.zeros((h, w), dtype=np.uint16)
    mosaic[0::2, 0::2] = 2048  # R
    mosaic[0::2, 1::2] = 4096  # G1
    mosaic[1::2, 1::2] = 6144  # B
    mosaic[1::2, 0::2] = 8192  # G2
    cfa = make_rggb_cfa(h, w)
    black = [0, 0, 0, 0]
    white = [16383, 16383, 16383, 16383]
    result = analyzer.analyze_mosaic(mosaic, cfa, black, white)
    assert result.channel_metrics["R"].p50 == pytest.approx(2048 / 16383)
    assert result.channel_metrics["B"].p50 == pytest.approx(6144 / 16383)


# ---------------------------------------------------------------- percentiles


def test_hot_pixel_does_not_collapse_p999(analyzer):
    Given = "a mosaic with a single saturated hot pixel"
    When = "P99.9 is computed"
    Then = "the P99.9 metric is unaffected by that single outlier"
    h = w = 100
    mosaic = make_uniform_mosaic(h, w, 8192)
    mosaic[50, 50] = 16383  # hot pixel (on an R position)
    cfa = make_rggb_cfa(h, w)
    result = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383)
    r = result.channel_metrics["R"]
    # P99.9 of 2500 R pixels is still the bulk value, not the hot pixel.
    assert r.p999 == pytest.approx((8192 - 512) / (16383 - 512), abs=1e-6)
    assert r.max_norm > r.p999  # the hot pixel shows in max, not in P99.9
    assert result.limiting_channel == "R"


def test_real_highlight_region_is_detected(analyzer):
    Given = "a large clipped white region (20% of the frame)"
    When = "clipping is measured"
    Then = "the clipped fraction is significant (region detected, not ignored)"
    h = w = 100
    mosaic = make_uniform_mosaic(h, w, 8192)
    mosaic[:, :20] = 16383  # 20% columns saturated
    cfa = make_rggb_cfa(h, w)
    result = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383)
    assert result.clipped_fraction > 0.19
    assert result.clipped_count > 0


def test_p9999_none_when_insufficient_pixels(analyzer):
    Given = "a channel with fewer than 10,000 pixels"
    When = "analysis runs"
    Then = "P99.99 is None and a warning is emitted"
    mosaic = make_uniform_mosaic(64, 64, 8192)
    cfa = make_rggb_cfa(64, 64)
    result = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383)
    assert result.channel_metrics["R"].p9999 is None
    assert any("P99.99 unavailable" in w for w in result.warnings)


def test_p9999_present_with_enough_pixels(analyzer):
    h = w = 200  # 200*200 = 40k total, ~10k per channel
    mosaic = make_gradient_mosaic(h, w, 512, 16383)
    cfa = make_rggb_cfa(h, w)
    result = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383)
    assert result.channel_metrics["R"].p9999 is not None


# ---------------------------------------------------------------- limiting channel


def test_limiting_channel_is_highest_p999(analyzer):
    h = w = 100
    mosaic = make_uniform_mosaic(h, w, 8192)
    mosaic[1::2, 1::2] = 12000  # B brighter
    cfa = make_rggb_cfa(h, w)
    result = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383)
    assert result.limiting_channel == "B"
    assert result.measured_normalized == pytest.approx(
        (12000 - 512) / (16383 - 512)
    )


# ---------------------------------------------------------------- clipping thresholds


def test_clip_thresholds(analyzer):
    Given = "values around the near/hard clip thresholds"
    When = "analysis runs with defaults (near=0.95, hard=0.995)"
    Then = "hard clip is >= hard threshold, near clip is in [near, hard)"
    black, white = 0, 1000
    mosaic = make_uniform_mosaic(100, 100, 960)  # normalized 0.96 -> near, not hard
    cfa = make_rggb_cfa(100, 100)
    result = analyzer.analyze_mosaic(mosaic, cfa, black, white)
    assert result.clipped_fraction == 0.0
    assert result.near_clipped_fraction > 0.9

    mosaic2 = make_uniform_mosaic(100, 100, 998)  # normalized 0.998 -> hard
    result2 = analyzer.analyze_mosaic(mosaic2, cfa, black, white)
    assert result2.clipped_fraction > 0.9
    assert result2.near_clipped_fraction == 0.0


# ---------------------------------------------------------------- ROI


def test_center_crop_roi(analyzer):
    Given = "a CENTER_CROP ROI"
    When = "analysis runs"
    Then = "the ROI is the central half and dimensions shrink accordingly"
    h = w = 100
    mosaic = make_uniform_mosaic(h, w, 8192)
    cfa = make_rggb_cfa(h, w)
    result = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383, Roi(RoiType.CENTER_CROP))
    assert result.raw_width == 50
    assert result.raw_height == 50
    assert result.roi is not None


def test_configured_roi(analyzer):
    h = w = 100
    mosaic = make_uniform_mosaic(h, w, 8192)
    mosaic[:, :10] = 16383  # clipped only in left 10 columns
    cfa = make_rggb_cfa(h, w)
    roi = Roi(RoiType.CONFIGURED_ROI, 50, 0, 50, 100)  # right half, no clip
    result = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383, roi)
    assert result.clipped_fraction == 0.0
    full = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383)
    assert full.clipped_fraction > 0.0


# ---------------------------------------------------------------- error cases


def test_non_bayer_cfa_rejected(analyzer):
    h = w = 8
    mosaic = make_uniform_mosaic(h, w, 8192)
    cfa = np.full((h, w), 4, dtype=np.int64)  # X-Trans style index
    with pytest.raises(ValueError):
        analyzer.analyze_mosaic(mosaic, cfa, 512, 16383)


def test_shape_mismatch_rejected(analyzer):
    mosaic = make_uniform_mosaic(8, 8, 8192)
    cfa = make_rggb_cfa(4, 4)
    with pytest.raises(ValueError):
        analyzer.analyze_mosaic(mosaic, cfa, 512, 16383)


def test_invalid_white_level_rejected(analyzer):
    mosaic = make_uniform_mosaic(8, 8, 8192)
    cfa = make_rggb_cfa(8, 8)
    with pytest.raises(ValueError):
        analyzer.analyze_mosaic(mosaic, cfa, 512, 512)  # white == black


# ---------------------------------------------------------------- metadata


def test_metadata_exposure_passthrough(analyzer):
    mosaic = make_uniform_mosaic(8, 8, 8192)
    cfa = make_rggb_cfa(8, 8)
    meta = ExposureSettings(iso=100, aperture=8.0, shutter_seconds=0.025)
    result = analyzer.analyze_mosaic(mosaic, cfa, 512, 16383, metadata_exposure=meta)
    assert result.metadata_exposure == meta

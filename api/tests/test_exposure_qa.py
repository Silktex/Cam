"""
Tests for ExposureQaService and the exposure state machine.
"""
import pytest

from app.services.exposure.config import AutoExposureConfig
from app.services.exposure.qa import ExposureQaService, QaResult
from app.services.exposure.state_machine import (
    AutoExposureStateMachine,
    ExposureState,
)
from app.services.exposure.types import (
    ExposureAnalysisResult,
    ExposureSettings,
    QaStatus,
)


@pytest.fixture
def qa():
    return ExposureQaService(AutoExposureConfig.defaults())


@pytest.fixture
def locked():
    return ExposureSettings(iso=100, aperture=8.0, shutter_seconds=0.025)


def make_analysis(
    measured=0.75,
    clipped_fraction=0.0,
    near_clipped_fraction=0.0,
    underexposed_fraction=0.0,
    iso=100,
    aperture=8.0,
    shutter=0.025,
    status="OK",
):
    r = ExposureAnalysisResult()
    r.status = status
    r.measured_normalized = measured
    r.clipped_fraction = clipped_fraction
    r.near_clipped_fraction = near_clipped_fraction
    r.underexposed_fraction = underexposed_fraction
    r.metadata_exposure = ExposureSettings(
        iso=iso, aperture=aperture, shutter_seconds=shutter
    )
    return r


# ---------------------------------------------------------------- QA states


def test_pass_when_within_limits(qa, locked):
    result = qa.evaluate(make_analysis(), locked)
    assert result.status == QaStatus.PASS


def test_fail_on_hard_clipping(qa, locked):
    result = qa.evaluate(make_analysis(clipped_fraction=0.001), locked)
    assert result.status == QaStatus.FAIL
    assert "clipping" in result.reason


def test_fail_on_exposure_drift(qa, locked):
    result = qa.evaluate(make_analysis(iso=800), locked)
    assert result.status == QaStatus.FAIL
    assert "drift" in result.reason


def test_drift_detected_for_shutter(qa, locked):
    result = qa.evaluate(make_analysis(shutter=0.05), locked)
    assert result.status == QaStatus.FAIL
    assert "shutter" in result.reason


def test_retake_when_minor_clipping_within_limit(qa, locked):
    result = qa.evaluate(make_analysis(clipped_fraction=0.00001), locked, retake_count=0)
    assert result.status == QaStatus.RETAKE


def test_fail_when_retake_limit_exceeded(qa, locked):
    result = qa.evaluate(make_analysis(clipped_fraction=0.00001), locked, retake_count=2)
    assert result.status == QaStatus.FAIL


def test_warning_when_near_clipping(qa, locked):
    result = qa.evaluate(make_analysis(near_clipped_fraction=0.002), locked)
    assert result.status == QaStatus.WARNING


def test_warning_when_signal_low(qa, locked):
    result = qa.evaluate(make_analysis(measured=0.4), locked)
    assert result.status == QaStatus.WARNING


def test_fail_on_raw_decode_error(qa, locked):
    result = qa.evaluate(make_analysis(status="RAW_DECODE_FAILED"), locked)
    assert result.status == QaStatus.FAIL


def test_fail_on_underexposure(qa, locked):
    result = qa.evaluate(make_analysis(underexposed_fraction=0.9), locked)
    assert result.status == QaStatus.FAIL


# ---------------------------------------------------------------- state machine


def test_state_machine_happy_path():
    Given = "a normal capture lifecycle"
    When = "the state machine walks IDLE -> ... -> COMPLETE"
    Then = "every transition is accepted"
    sm = AutoExposureStateMachine()
    path = [
        ExposureState.CONFIGURING_CAMERA,
        ExposureState.PREFLIGHT_CAPTURING,
        ExposureState.PREFLIGHT_ANALYZING,
        ExposureState.ADJUSTING_EXPOSURE,
        ExposureState.PREFLIGHT_CAPTURING,
        ExposureState.PREFLIGHT_ANALYZING,
        ExposureState.LOCKED,
        ExposureState.PRODUCTION_CAPTURING,
        ExposureState.FRAME_QA,
        ExposureState.COMPLETE,
    ]
    for s in path:
        assert sm.transition(s), f"failed to transition to {s}"
    assert sm.is_complete


def test_state_machine_rejects_illegal_transition():
    sm = AutoExposureStateMachine()
    assert not sm.transition(ExposureState.COMPLETE)  # IDLE -> COMPLETE illegal
    assert sm.state == ExposureState.IDLE


def test_state_machine_failure_state():
    sm = AutoExposureStateMachine()
    sm.transition(ExposureState.CONFIGURING_CAMERA)
    sm.transition(ExposureState.FAILED_CAMERA_CONFIG)
    assert sm.is_failed

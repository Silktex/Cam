"""
Auto Exposure state machine.

Tracks the deterministic lifecycle of an exposure-controlled capture sequence
so transitions are explicit and logged rather than implicit (PRD §22).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ExposureState(str, Enum):
    IDLE = "IDLE"
    CONFIGURING_CAMERA = "CONFIGURING_CAMERA"
    PREFLIGHT_CAPTURING = "PREFLIGHT_CAPTURING"
    PREFLIGHT_ANALYZING = "PREFLIGHT_ANALYZING"
    ADJUSTING_EXPOSURE = "ADJUSTING_EXPOSURE"
    LOCKED = "LOCKED"
    PRODUCTION_CAPTURING = "PRODUCTION_CAPTURING"
    FRAME_QA = "FRAME_QA"
    COMPLETE = "COMPLETE"
    FAILED_CAMERA_CONFIG = "FAILED_CAMERA_CONFIG"
    FAILED_RAW_DECODE = "FAILED_RAW_DECODE"
    FAILED_NON_CONVERGENCE = "FAILED_NON_CONVERGENCE"
    FAILED_CLIPPING = "FAILED_CLIPPING"
    FAILED_UNDEREXPOSURE = "FAILED_UNDEREXPOSURE"
    FAILED_DYNAMIC_RANGE = "FAILED_DYNAMIC_RANGE"
    FAILED_EXPOSURE_DRIFT = "FAILED_EXPOSURE_DRIFT"
    FAILED_LED_STATE = "FAILED_LED_STATE"
    FAILED_CAPTURE = "FAILED_CAPTURE"


# Legal transitions. A missing pair means the transition is rejected.
_TRANSITIONS = {
    ExposureState.IDLE: {ExposureState.CONFIGURING_CAMERA},
    ExposureState.CONFIGURING_CAMERA: {
        ExposureState.PREFLIGHT_CAPTURING,
        ExposureState.FAILED_CAMERA_CONFIG,
    },
    ExposureState.PREFLIGHT_CAPTURING: {
        ExposureState.PREFLIGHT_ANALYZING,
        ExposureState.FAILED_CAPTURE,
    },
    ExposureState.PREFLIGHT_ANALYZING: {
        ExposureState.ADJUSTING_EXPOSURE,
        ExposureState.LOCKED,
        ExposureState.FAILED_RAW_DECODE,
        ExposureState.FAILED_NON_CONVERGENCE,
        ExposureState.FAILED_DYNAMIC_RANGE,
    },
    ExposureState.ADJUSTING_EXPOSURE: {
        ExposureState.PREFLIGHT_CAPTURING,
        ExposureState.FAILED_NON_CONVERGENCE,
    },
    ExposureState.LOCKED: {
        ExposureState.PRODUCTION_CAPTURING,
        ExposureState.FAILED_CAMERA_CONFIG,
    },
    ExposureState.PRODUCTION_CAPTURING: {
        ExposureState.FRAME_QA,
        ExposureState.FAILED_CAPTURE,
        ExposureState.FAILED_LED_STATE,
    },
    ExposureState.FRAME_QA: {
        ExposureState.PRODUCTION_CAPTURING,
        ExposureState.COMPLETE,
        ExposureState.FAILED_CLIPPING,
        ExposureState.FAILED_UNDEREXPOSURE,
        ExposureState.FAILED_EXPOSURE_DRIFT,
        ExposureState.FAILED_RAW_DECODE,
    },
    ExposureState.COMPLETE: set(),
}


@dataclass
class AutoExposureStateMachine:
    state: ExposureState = ExposureState.IDLE
    history: List[ExposureState] = field(default_factory=list)

    def transition(self, next_state: ExposureState) -> bool:
        """Attempt a transition; returns True on success, False if illegal."""
        if next_state not in _TRANSITIONS.get(self.state, set()):
            return False
        self.history.append(self.state)
        self.state = next_state
        return True

    @property
    def is_failed(self) -> bool:
        return self.state.value.startswith("FAILED_")

    @property
    def is_complete(self) -> bool:
        return self.state == ExposureState.COMPLETE

"""Error-visibility tests for the batch-capture failure cleanup path.

Pins the observable behavior of ``BatchCaptureService.start_batch_capture``
when the capture sequence fails AND the emergency lights-off cleanup in the
outer except block (batch_capture_service.py) also fails:

* the ORIGINAL batch failure must propagate to the caller,
* the emergency lights-off must still be attempted,
* a lights-off failure must not mask the original error,
* the lights-off failure must be visible in ERROR-level logs (not silently
  swallowed by a bare ``except:``).

All light/camera singletons are neutralized — these tests never touch
hardware or the network.
"""
import asyncio
import logging

import pytest

from app.services import batch_capture_service as batch_module
from app.services.batch_capture_service import BatchCaptureService


class BatchStepError(RuntimeError):
    """Original batch-path failure (e.g. light rig fault before capture)."""


class CleanupError(RuntimeError):
    """Emergency lights-off cleanup failure (e.g. ESP32 unreachable)."""


def _make_service(monkeypatch):
    """Fresh service with hardware singletons neutralized.

    ``_set_all_lights_off`` is stubbed so the FIRST call (pre-capture
    "turn off all lights", line ~91) raises ``BatchStepError`` — landing in
    the outer except handler — and the SECOND call (emergency cleanup inside
    that handler) raises ``CleanupError``.
    """
    svc = BatchCaptureService()

    calls = {"lights_off": 0}

    async def fake_lights_off():
        calls["lights_off"] += 1
        if calls["lights_off"] == 1:
            raise BatchStepError("light rig fault before capture")
        raise CleanupError("ESP32 unreachable during emergency lights-off")

    monkeypatch.setattr(svc, "_set_all_lights_off", fake_lights_off)

    # Skip light_service.connect() — never touch the ESP32 network.
    monkeypatch.setattr(batch_module.light_service, "connected", True)

    # Force-disable the auto-exposure preflight regardless of environment.
    monkeypatch.setattr(batch_module.settings, "AUTO_EXPOSURE_ENABLED", False)

    return svc, calls


def _run_batch(svc):
    asyncio.run(
        svc.start_batch_capture(folder="test_folder", prefix="test", light_stabilize_delay=0.0)
    )


def test_original_error_propagates_when_emergency_lights_off_also_fails(monkeypatch):
    """Characterization: the batch failure propagates even when the emergency
    lights-off cleanup fails too (cleanup error is swallowed, not raised)."""
    svc, calls = _make_service(monkeypatch)

    with pytest.raises(BatchStepError, match="light rig fault"):
        _run_batch(svc)

    assert calls["lights_off"] == 2


def test_cleanup_error_does_not_mask_original_error(monkeypatch):
    """Characterization: the propagated exception is the ORIGINAL batch
    failure, never the CleanupError raised by the emergency lights-off."""
    svc, calls = _make_service(monkeypatch)

    with pytest.raises(BatchStepError):
        _run_batch(svc)

    # If the cleanup error had masked the original, CleanupError would have
    # escaped instead and the pytest.raises above would already have failed.
    assert calls["lights_off"] == 2


def test_emergency_lights_off_failure_is_logged(monkeypatch, caplog):
    """NEW behavior: the emergency lights-off failure must produce an
    ERROR-level log record mentioning the lights-off failure — it must not
    be silently swallowed by a bare ``except:``.

    (The original batch failure is already logged via ``logger.exception``
    just above; this asserts the SECOND failure gets visibility too.)
    """
    svc, calls = _make_service(monkeypatch)

    with caplog.at_level(
        logging.ERROR, logger="app.services.batch_capture_service"
    ):
        with pytest.raises(BatchStepError):
            _run_batch(svc)

    assert calls["lights_off"] == 2

    lights_off_failures = [
        r for r in caplog.records
        if r.levelno >= logging.ERROR and "turn off lights" in r.getMessage()
    ]
    assert lights_off_failures, (
        "Emergency lights-off failure was swallowed silently — expected an "
        f"ERROR log mentioning it. Got records: "
        f"{[r.getMessage() for r in caplog.records]}"
    )
    # The log must carry the cleanup failure's context.
    assert "ESP32 unreachable" in lights_off_failures[0].getMessage()

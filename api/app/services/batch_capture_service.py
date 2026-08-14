"""
Batch Capture Service
Orchestrates light control and camera capture for multi-light photography.
"""
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable, Awaitable
from dataclasses import dataclass, field

from app.config import settings
from app.services.light_service import light_service
from app.services.camera_service import camera_service
from app.models.batch_capture import BatchCaptureProgress, BatchCaptureResult

logger = logging.getLogger(__name__)


@dataclass
class BatchCaptureState:
    """Tracks state of an ongoing batch capture"""
    is_running: bool = False
    should_cancel: bool = False
    current_step: int = 0
    total_steps: int = 9  # Top Light + 8 Side Lights
    captures: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    phase: str = "capturing"  # "capturing" or "downloading"
    progress_callback: Optional[Callable[[BatchCaptureProgress], Awaitable[None]]] = None


class BatchCaptureService:
    """Manages batch capture sessions with coordinated light and camera control."""

    def __init__(self):
        self._state = BatchCaptureState()
        self._lock = asyncio.Lock()
        
        # Light indices: Top Light = 0, Side 1-8 = 1-8
        self.TOP_LIGHT_ID = 0
        self.SIDE_LIGHT_IDS = list(range(1, 9))  # Side 1 Light to Side 8 Light

    @property
    def is_running(self) -> bool:
        return self._state.is_running

    async def start_batch_capture(
        self,
        folder: str,
        prefix: str = "batch",
        light_stabilize_delay: float = 2.0,
        profile: str = "CHECKER-17FEB.npz",
        progress_callback: Optional[Callable[[BatchCaptureProgress], Awaitable[None]]] = None
    ) -> BatchCaptureResult:
        """
        Execute a full batch capture sequence:
        1. Top Light ON, wait, capture with suffix "top", Top Light OFF
        2. Side 1 ON, wait, capture with suffix "side_1", Side 1 OFF
        3. Repeat through Side 8
        Each light turns on, captures, then turns off before the next.
        """
        async with self._lock:
            if self._state.is_running:
                raise Exception("Batch capture already in progress")

            self._state = BatchCaptureState(
                is_running=True,
                should_cancel=False,
                current_step=0,
                total_steps=9,  # Top Light + 8 Side Lights
                captures=[],
                errors=[],
                started_at=datetime.now(),
                phase="capturing",
                progress_callback=progress_callback
            )

        focus_locked = False
        try:
            logger.info(f"Starting batch capture: folder={folder}, prefix={prefix}")

            # Ensure lights are connected
            if not light_service.connected:
                await light_service.connect()

            # Turn off all lights first
            await self._set_all_lights_off()
            await asyncio.sleep(0.5)

            # Build list of all lights to capture: Top Light (id=0) + Side Lights (id=1-8)
            all_lights = [
                {"id": self.TOP_LIGHT_ID, "name": "Top Light", "suffix": "top"},
            ] + [
                {"id": side_id, "name": f"Side {side_id} Light", "suffix": f"side_{side_id}"}
                for side_id in self.SIDE_LIGHT_IDS
            ]

            loop = asyncio.get_event_loop()

            # --- Auto exposure preflight (feature-gated) ---
            # Determine ONE locked exposure and hold it for the whole sequence.
            exposure_cfg = settings.auto_exposure_config()
            locked_exposure = None
            if exposure_cfg.enabled:
                from app.services.exposure.service import (
                    RIG_LIGHTS,
                    build_services,
                    run_preflight,
                )
                from app.services.exposure.types import ExposureSettings

                services = build_services(exposure_cfg)
                preflight_result = await loop.run_in_executor(
                    None, run_preflight, services, RIG_LIGHTS
                )
                if preflight_result.status != "PASS":
                    raise Exception(
                        f"Exposure preflight failed: {preflight_result.status} — "
                        f"{'; '.join(preflight_result.errors)}"
                    )
                locked_exposure = ExposureSettings(
                    iso=preflight_result.iso,
                    aperture=preflight_result.aperture,
                    shutter_seconds=preflight_result.selected_shutter_seconds,
                    shutter_label=preflight_result.selected_shutter_label,
                    camera_mode="Manual",
                )
                logger.info(
                    f"Auto exposure locked: {preflight_result.selected_shutter_label} "
                    f"(limiting light {preflight_result.limiting_light})"
                )

            # --- Focus once, lock for batch ---
            # The first capture (Top Light) runs with focusmode=Automatic,
            # so the camera autofocuses naturally during capture().
            # After that first capture succeeds, we switch to Manual to
            # lock focus for the remaining 8 shots.  This avoids the
            # trigger_autofocus() toggle which corrupts Sony's PTP state.

            # Collect raw capture info for deferred post-processing
            raw_captures = []

            # Stop live view before batch to avoid lock contention and PTP races.
            # capture_image() also stops it, but doing it once upfront is cleaner.
            if camera_service.live_view_active:
                logger.info("Stopping live view before batch capture")
                await loop.run_in_executor(None, camera_service.stop_live_view)
                await asyncio.sleep(0.5)

            # NOTE: No pre-focus step. Sony PTP rejects all AF triggers
            # (autofocus toggle, d2c1 ShutterHalfRelease) — they corrupt
            # the PTP session. The camera's native AF runs during capture()
            # on the first shot (focusmode=Automatic). It may take longer
            # if the lens is far from focus, but it's reliable.

            # ======= Capture + download per image =======
            # Sony PTP only keeps the most recent capture accessible,
            # so we must download immediately after each capture.
            # Focus-once still saves ~4-8s of AF time across 9 shots.
            self._state.phase = "capturing"
            prev_light_id = None
            for step, light_info in enumerate(all_lights, start=1):
                if self._state.should_cancel:
                    logger.info("Batch capture cancelled by user")
                    break

                self._state.current_step = step
                light_id = light_info["id"]
                light_name = light_info["name"]
                suffix = light_info["suffix"]

                # Switch lights (turn off previous, turn on current)
                t_step_start = time.time()
                if prev_light_id is not None:
                    await self._set_light(prev_light_id, on=False)
                await self._set_light(light_id, on=True, brightness=100)
                t_light = time.time()

                # Report progress: waiting for light
                await self._report_progress(
                    status="waiting_light",
                    message=f"Waiting {light_stabilize_delay}s for {light_name} to stabilize..."
                )

                # Wait for light to stabilize
                await asyncio.sleep(light_stabilize_delay)
                t_delay = time.time()

                if self._state.should_cancel:
                    break

                # Report progress: capturing
                await self._report_progress(
                    status="capturing",
                    message=f"Capturing with {light_name}..."
                )

                # Capture image — uses capture_image which handles capture+download
                # but skip_post_process defers RAW→JPG to background
                try:
                    result = await loop.run_in_executor(
                        None,
                        lambda s=suffix: camera_service.capture_image(
                            folder=folder, prefix=prefix, suffix=s,
                            skip_post_process=True,
                        )
                    )
                    t_capture = time.time()
                    logger.info(f"[TIMING] {light_name} (step {step}/9): light={t_light-t_step_start:.2f}s delay={t_delay-t_light:.2f}s capture={t_capture-t_delay:.2f}s TOTAL={t_capture-t_step_start:.2f}s")

                    if result.get("success"):
                        capture_info = {
                            "step": step,
                            "light_id": light_id,
                            "light_name": light_name,
                            "suffix": suffix,
                            "filename": result.get("filename"),
                            "file_url": result.get("file_url"),
                            "file_size": result.get("file_size"),
                            "captured_at": result.get("captured_at")
                        }
                        self._state.captures.append(capture_info)
                        logger.info(f"Captured: {result.get('filename')} ({step}/9)")

                        # Per-frame exposure QA.
                        if exposure_cfg.enabled and locked_exposure is not None:
                            qa_status = await self._qa_frame(
                                result.get("filepath"), locked_exposure, services
                            )
                            capture_info["exposure_qa"] = qa_status
                            if qa_status in ("FAIL", "RETAKE"):
                                error_msg = (
                                    f"Exposure QA {qa_status} for {light_name}: "
                                    f"{result.get('filename')}"
                                )
                                self._state.errors.append(error_msg)
                                logger.error(error_msg)

                        raw_captures.append({
                            "folder_path": result.get("folder_path"),
                            "raw_filename": result.get("filename"),
                            "ext": result.get("ext"),
                        })

                        # After first successful capture, lock focus to Manual.
                        # The first capture ran in AF mode so the camera focused
                        # naturally.  Now lock that focus distance for the rest.
                        if step == 1 and not focus_locked:
                            try:
                                await loop.run_in_executor(
                                    None, camera_service.set_setting, 'focusmode', 'Manual'
                                )
                                focus_locked = True
                                logger.info("Focus locked to Manual after first capture")
                            except Exception as e:
                                logger.warning(f"Focus lock failed: {e}")

                        await self._report_progress(
                            status="processing",
                            message=f"Captured {light_name} ({step}/9)"
                        )
                    else:
                        error_msg = f"Capture failed for {light_name}: {result.get('error')}"
                        self._state.errors.append(error_msg)
                        logger.error(error_msg)

                        await self._report_progress(
                            status="error",
                            message=error_msg
                        )

                except Exception as e:
                    error_msg = f"Capture exception for {light_name}: {str(e)}"
                    self._state.errors.append(error_msg)
                    logger.exception(error_msg)

                prev_light_id = light_id

            # Turn off all lights
            logger.info("Batch capture complete, turning off all lights")
            await self._set_all_lights_off()

            # Queue calibration + crop in background thread
            # (JPG conversion skipped — render_image() serves calibrated images on demand)
            if raw_captures:
                import threading
                def _background_calibrate(batch_folder, profile_name):
                    try:
                        from app.services.post_capture_service import post_capture_service
                        post_capture_service.queue(batch_folder, profile=profile_name)
                        logger.info(f"Queued calibrate+crop for {batch_folder} with profile {profile_name}")
                    except Exception as e:
                        logger.warning(f"Failed to queue post-capture processing: {e}")

                threading.Thread(
                    target=_background_calibrate,
                    args=(folder, profile),
                    daemon=True,
                ).start()
                logger.info(f"Calibrate+crop queued in background")

            # Build result
            completed_at = datetime.now()
            duration = (completed_at - self._state.started_at).total_seconds()

            result = BatchCaptureResult(
                success=len(self._state.errors) == 0,
                folder=folder,
                total_captures=len(self._state.captures),
                captures=self._state.captures,
                started_at=self._state.started_at.isoformat(),
                completed_at=completed_at.isoformat(),
                duration_seconds=duration,
                errors=self._state.errors
            )

            await self._report_progress(
                status="complete",
                message=f"Batch capture complete: {len(self._state.captures)} images in {duration:.1f}s"
            )

            return result

        except Exception as e:
            logger.exception(f"Batch capture failed: {e}")
            # Ensure lights are off on error
            try:
                await self._set_all_lights_off()
            except:
                pass
            raise

        finally:
            # Restore AF mode if we locked focus
            if focus_locked:
                try:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, camera_service.set_setting, 'focusmode', 'Automatic')
                    logger.info("Restored focus mode to Automatic")
                except Exception as e:
                    logger.warning(f"Failed to restore AF mode: {e}")
            self._state.is_running = False

    async def cancel(self):
        """Cancel an ongoing batch capture.

        Sets the cancel flag and asks the camera worker to stop at its next
        safe cancellation point.
        """
        if self._state.is_running:
            self._state.should_cancel = True
            logger.info("Batch capture cancellation requested")
            camera_service.request_operation_cancel()

            return {"success": True, "message": "Cancellation requested"}
        return {"success": False, "message": "No batch capture in progress"}

    def get_status(self) -> dict:
        """Get current batch capture status"""
        return {
            "is_running": self._state.is_running,
            "current_step": self._state.current_step,
            "total_steps": self._state.total_steps,
            "captures_completed": len(self._state.captures),
            "errors": len(self._state.errors),
            "phase": self._state.phase,
        }

    async def _set_light(self, light_id: int, on: bool, brightness: int = 100):
        """Set a single light state"""
        await light_service.set_light(light_id, on=on, brightness=brightness if on else None)

    async def _qa_frame(self, raw_path, locked_exposure, services) -> str:
        """Analyze a captured RAW and return its exposure QA status string."""
        loop = asyncio.get_event_loop()

        def _run():
            from pathlib import Path

            analysis = services.analyzer.analyze_file(Path(raw_path))
            return services.qa.evaluate(analysis, locked_exposure)

        result = await loop.run_in_executor(None, _run)
        return result.status.value

    async def _set_all_lights_off(self):
        """Turn off all lights"""
        await light_service.set_all_lights(on=False)

    async def _report_progress(self, status: str, message: str, light_name: str = None):
        """Report progress to callback if registered"""
        if self._state.progress_callback:
            # Determine current light name
            if light_name is None:
                if self._state.current_step == 0:
                    light_name = "None"
                elif self._state.current_step == 1:
                    light_name = "Top Light"
                else:
                    light_name = f"Side {self._state.current_step - 1} Light"
            
            progress = BatchCaptureProgress(
                current_step=self._state.current_step,
                total_steps=self._state.total_steps,
                current_light=light_name,
                status=status,
                message=message,
                phase=self._state.phase,
                captures=[c.get("filename", "") for c in self._state.captures]
            )
            try:
                await self._state.progress_callback(progress)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")


# Singleton instance
batch_capture_service = BatchCaptureService()

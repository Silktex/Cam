"""
Batch Capture Service
Orchestrates light control and camera capture for multi-light photography.
"""
import asyncio
import logging
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
                progress_callback=progress_callback
            )

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
            
            # Collect raw capture info for deferred post-processing
            raw_captures = []

            # Helper: run camera prep in executor (camera ops are blocking)
            async def _prep_camera():
                """Drain events + ensure camera is responsive."""
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, camera_service._drain_camera_events, 200)

            prev_light_id = None
            for step, light_info in enumerate(all_lights, start=1):
                if self._state.should_cancel:
                    logger.info("Batch capture cancelled by user")
                    break

                self._state.current_step = step
                light_id = light_info["id"]
                light_name = light_info["name"]
                suffix = light_info["suffix"]

                # Run light switch + camera prep concurrently
                async def _switch_lights():
                    if prev_light_id is not None:
                        await self._set_light(prev_light_id, on=False)
                    await self._set_light(light_id, on=True, brightness=100)

                await asyncio.gather(_switch_lights(), _prep_camera())
                logger.info(f"{light_name} ON")

                # Report progress: waiting for light
                await self._report_progress(
                    status="waiting_light",
                    message=f"Waiting {light_stabilize_delay}s for {light_name} to stabilize..."
                )

                # Wait for light to stabilize
                await asyncio.sleep(light_stabilize_delay)

                if self._state.should_cancel:
                    break

                # Report progress: capturing
                await self._report_progress(
                    status="capturing",
                    message=f"Capturing with {light_name}..."
                )

                # Capture image — post-processing deferred to background
                try:
                    result = camera_service.capture_image(
                        folder=folder, prefix=prefix, suffix=suffix,
                        skip_post_process=True,
                    )

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
                        logger.info(f"Captured: {result.get('filename')}")

                        # Collect info for deferred post-processing
                        raw_captures.append({
                            "folder_path": result.get("folder_path"),
                            "raw_filename": result.get("filename"),
                            "ext": result.get("ext"),
                        })

                        # Report progress
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

            # Turn off all lights at the end
            logger.info("Batch capture complete, turning off all lights")
            await self._set_all_lights_off()

            # Defer RAW→JPG + calibrate+crop to background thread
            if raw_captures:
                import threading
                def _background_post_process(captures, batch_folder):
                    for capture in captures:
                        try:
                            camera_service._post_process_image(
                                Path(capture["folder_path"]),
                                capture["raw_filename"],
                                capture["ext"],
                            )
                        except Exception as pp_err:
                            logger.warning(f"Post-processing failed for {capture['raw_filename']}: {pp_err}")
                    # Queue calibration + crop after JPGs are ready
                    try:
                        from app.services.post_capture_service import post_capture_service
                        post_capture_service.queue(batch_folder)
                        logger.info(f"Queued calibrate+crop for {batch_folder}")
                    except Exception as e:
                        logger.warning(f"Failed to queue post-capture processing: {e}")

                threading.Thread(
                    target=_background_post_process,
                    args=(raw_captures, folder),
                    daemon=True,
                ).start()
                logger.info(f"RAW→JPG + calibrate+crop dispatched to background")

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
            self._state.is_running = False

    async def cancel(self):
        """Cancel an ongoing batch capture"""
        if self._state.is_running:
            self._state.should_cancel = True
            logger.info("Batch capture cancellation requested")
            return {"success": True, "message": "Cancellation requested"}
        return {"success": False, "message": "No batch capture in progress"}

    def get_status(self) -> dict:
        """Get current batch capture status"""
        return {
            "is_running": self._state.is_running,
            "current_step": self._state.current_step,
            "total_steps": self._state.total_steps,
            "captures_completed": len(self._state.captures),
            "errors": len(self._state.errors)
        }

    async def _set_light(self, light_id: int, on: bool, brightness: int = 100):
        """Set a single light state"""
        await light_service.set_light(light_id, on=on, brightness=brightness if on else None)

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
                captures=[c.get("filename", "") for c in self._state.captures]
            )
            try:
                await self._state.progress_callback(progress)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")


# Singleton instance
batch_capture_service = BatchCaptureService()

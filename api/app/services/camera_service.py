"""
Camera Service - Thread-safe singleton for Sony A7R III control via gphoto2
Simplified version with single lock and no keep-alive complexity
"""

import gphoto2 as gp
import subprocess
import time
import logging
import threading
import atexit
import signal
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Generator
from threading import Lock, Event

from app.config import settings
from app.services.event_bus import event_bus, EventType

logger = logging.getLogger(__name__)


class CameraService:
    """Thread-safe singleton camera controller"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._camera = None
        self._context = None
        self._connected = False
        self._model = None
        
        # Single lock for all camera operations
        self._lock = Lock()
        
        # Live view control
        self._stop_live_view = Event()
        self._live_view_active = False
        
        self._initialized = True
        
        # Register cleanup on exit
        atexit.register(self._cleanup_on_exit)
        
        logger.info("CameraService initialized")
    
    def _cleanup_on_exit(self):
        """Ensure camera is released on process exit"""
        logger.info("Cleaning up camera on exit...")
        self._stop_live_view.set()
        self._cleanup_camera()
    
    # =========== Process Management ===========
    
    def kill_ptp_processes(self) -> List[str]:
        """Kill macOS PTP daemons that grab the camera USB"""
        killed = []
        for proc in settings.PTP_PROCESSES:
            try:
                result = subprocess.run(
                    ["killall", "-9", proc],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    killed.append(proc)
            except Exception:
                pass
        
        if killed:
            time.sleep(0.3)
        
        return killed
    
    def reset_usb(self) -> bool:
        """Reset USB device using gphoto2 --reset"""
        try:
            # First try gphoto2 reset
            result = subprocess.run(
                ["gphoto2", "--reset"],
                capture_output=True,
                text=True,
                timeout=10
            )
            logger.info(f"USB reset via gphoto2: {result.returncode == 0}")
            time.sleep(1)
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"USB reset failed: {e}")
            return False
    
    def detect_camera(self) -> bool:
        """Check if camera is detected via gphoto2 CLI"""
        try:
            result = subprocess.run(
                ["gphoto2", "--auto-detect"],
                capture_output=True,
                text=True,
                timeout=10
            )
            detected = "usb:" in result.stdout.lower()
            logger.info(f"Camera detection: {'found' if detected else 'not found'}")
            return detected
        except Exception as e:
            logger.error(f"Camera detection failed: {e}")
            return False
    
    def startup_check(self):
        """Run at startup to log camera status"""
        self.kill_ptp_processes()
        detected = self.detect_camera()
        if detected:
            logger.info("✓ Camera detected at startup")
        else:
            logger.warning("✗ No camera detected at startup")
    
    # =========== Connection ===========
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self._camera is not None
    
    @property
    def model(self) -> Optional[str]:
        return self._model
    
    def connect(self) -> Dict[str, Any]:
        """Connect to camera"""
        with self._lock:
            if self._connected:
                return {
                    "success": True,
                    "connected": True,
                    "model": self._model,
                    "message": "Already connected"
                }
            
            # Kill PTP grabbers first
            self.kill_ptp_processes()
            time.sleep(0.5)
            
            # Try to connect with retries
            max_retries = 3
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"Connection attempt {attempt + 1}/{max_retries}")
                    
                    self._context = gp.Context()
                    self._camera = gp.Camera()
                    self._camera.init(self._context)
                    
                    # Get camera model
                    abilities = self._camera.get_abilities()
                    self._model = abilities.model
                    self._connected = True
                    
                    # Set manual focus to prevent AF blocking shutter
                    self._set_manual_focus()
                    
                    logger.info(f"✓ Connected to {self._model}")
                    event_bus.publish(EventType.CAMERA_CONNECTED, {"model": self._model})
                    
                    return {
                        "success": True,
                        "connected": True,
                        "model": self._model,
                        "message": f"Connected to {self._model}"
                    }
                    
                except gp.GPhoto2Error as e:
                    last_error = e
                    logger.warning(f"Attempt {attempt + 1} failed: {e}")
                    self._cleanup_camera()
                    if attempt < max_retries - 1:
                        self.kill_ptp_processes()
                        time.sleep(1)
            
            error_msg = f"Failed to connect after {max_retries} attempts: {last_error}"
            logger.error(error_msg)
            return {
                "success": False,
                "connected": False,
                "model": None,
                "message": error_msg
            }
    
    def disconnect(self) -> Dict[str, Any]:
        """Disconnect from camera"""
        with self._lock:
            self._stop_live_view.set()
            self._cleanup_camera()
            event_bus.publish(EventType.CAMERA_DISCONNECTED, {})
            
            return {
                "success": True,
                "connected": False,
                "message": "Disconnected"
            }
    
    def _cleanup_camera(self):
        """Internal cleanup of camera resources"""
        if self._camera:
            try:
                self._camera.exit(self._context)
            except Exception:
                pass
        self._camera = None
        self._context = None
        self._connected = False
        self._model = None
    
    def _set_manual_focus(self):
        """Set camera to manual focus to prevent AF blocking shutter"""
        try:
            config = self._camera.get_config(self._context)
            focus_widget = config.get_child_by_name("focusmode")
            focus_widget.set_value("Manual")
            self._camera.set_config(config, self._context)
            logger.info("Set focus mode to Manual")
        except Exception as e:
            logger.debug(f"Could not set manual focus: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get camera status without locking"""
        detected = self.detect_camera()
        return {
            "connected": self._connected,
            "detected": detected,
            "model": self._model,
            "live_view_active": self._live_view_active
        }
    
    def troubleshoot(self) -> Dict[str, Any]:
        """Kill PTP processes, reset USB, and detect camera"""
        with self._lock:
            self._stop_live_view.set()
            self._cleanup_camera()
            
            # Kill processes
            killed = self.kill_ptp_processes()
            time.sleep(0.3)
            
            # Reset USB device
            usb_reset = self.reset_usb()
            time.sleep(0.5)
            
            # Kill again after reset (daemons may respawn)
            killed2 = self.kill_ptp_processes()
            killed.extend(killed2)
            time.sleep(0.3)
            
            detected = self.detect_camera()
            
            return {
                "success": True,
                "killed_processes": killed,
                "usb_reset": usb_reset,
                "camera_detected": detected,
                "message": f"Killed {len(killed)} processes. USB reset: {usb_reset}. Camera {'detected' if detected else 'not detected'}."
            }
    
    # =========== Settings ===========
    
    def get_settings(self) -> List[Dict[str, Any]]:
        """Get camera settings"""
        # Don't try to get settings while live view is active (would block)
        if self._live_view_active:
            return []
        
        # Try to acquire lock without blocking too long
        acquired = self._lock.acquire(timeout=2)
        if not acquired:
            return []
        
        try:
            if not self.is_connected:
                return []
            
            try:
                config = self._camera.get_config(self._context)
                return self._parse_config(config)
            except gp.GPhoto2Error as e:
                logger.warning(f"Failed to get settings: {e}")
                return []
        finally:
            self._lock.release()
    
    def set_setting(self, name: str, value: Any) -> Dict[str, Any]:
        """Set a camera setting"""
        with self._lock:
            if not self.is_connected:
                raise Exception("Camera not connected")
            
            try:
                config = self._camera.get_config(self._context)
                widget = config.get_child_by_name(name)
                
                # Type conversion based on widget type
                widget_type = widget.get_type()
                if widget_type == gp.GP_WIDGET_TOGGLE:
                    value = int(bool(value))
                elif widget_type == gp.GP_WIDGET_RANGE:
                    value = float(value)
                
                widget.set_value(value)
                self._camera.set_config(config, self._context)
                
                logger.info(f"Set {name} = {value}")
                event_bus.publish(EventType.SETTING_CHANGED, {"name": name, "value": value})
                
                return {"success": True, "name": name, "value": value}
                
            except gp.GPhoto2Error as e:
                raise Exception(f"Failed to set {name}: {e}")
    
    def _parse_config(self, widget, depth=0) -> List[Dict[str, Any]]:
        """Parse gphoto2 config widget tree"""
        results = []
        
        widget_type = widget.get_type()
        
        # Only include leaf nodes with values
        if widget_type in (gp.GP_WIDGET_TEXT, gp.GP_WIDGET_RADIO,
                           gp.GP_WIDGET_MENU, gp.GP_WIDGET_TOGGLE,
                           gp.GP_WIDGET_RANGE):
            item = {
                "name": widget.get_name(),
                "label": widget.get_label(),
                "type": self._widget_type_name(widget_type),
                "readonly": bool(widget.get_readonly()),
            }
            
            try:
                item["value"] = widget.get_value()
            except:
                item["value"] = None
            
            if widget_type in (gp.GP_WIDGET_RADIO, gp.GP_WIDGET_MENU):
                try:
                    item["choices"] = [widget.get_choice(i) for i in range(widget.count_choices())]
                except:
                    item["choices"] = []
            
            if widget_type == gp.GP_WIDGET_RANGE:
                try:
                    item["range"] = widget.get_range()
                except:
                    item["range"] = None
            
            results.append(item)
        
        # Recurse children
        for i in range(widget.count_children()):
            child = widget.get_child(i)
            results.extend(self._parse_config(child, depth + 1))
        
        return results
    
    def _widget_type_name(self, widget_type: int) -> str:
        """Convert widget type to string"""
        type_map = {
            gp.GP_WIDGET_TEXT: "text",
            gp.GP_WIDGET_RADIO: "radio",
            gp.GP_WIDGET_MENU: "menu",
            gp.GP_WIDGET_TOGGLE: "toggle",
            gp.GP_WIDGET_RANGE: "range",
        }
        return type_map.get(widget_type, "unknown")
    
    # =========== Capture ===========
    
    def capture_image(self, folder: str, prefix: str = "capture", suffix: str = "") -> Dict[str, Any]:
        """Capture a single image and save to folder/raw/ subfolder.
        
        Args:
            folder: Capture session folder name
            prefix: Filename prefix (e.g., 'fabric')
            suffix: Suffix placed before extension (e.g., 'top', 'side_1')
        """
        # Stop live view first (outside lock to avoid deadlock)
        if self._live_view_active:
            self._stop_live_view.set()
            # Wait for live view to stop
            for _ in range(30):  # Wait up to 3 seconds
                if not self._live_view_active:
                    break
                time.sleep(0.1)
            time.sleep(0.5)  # Extra settle time after live view stops
        
        with self._lock:
            # Create subfolder structure
            folder_path = settings.CAPTURES_DIR / folder
            raw_path = folder_path / "raw"
            raw_path.mkdir(parents=True, exist_ok=True)
            
            # Generate filename: prefix_timestamp_suffix.ext
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Retry capture up to 3 times
            max_retries = 3
            last_error = None
            
            for attempt in range(max_retries):
                # Ensure connection before each attempt
                if not self._connected or not self._camera:
                    self.kill_ptp_processes()
                    time.sleep(0.5)
                    try:
                        self._context = gp.Context()
                        self._camera = gp.Camera()
                        self._camera.init(self._context)
                        abilities = self._camera.get_abilities()
                        self._model = abilities.model
                        self._connected = True
                        self._set_manual_focus()
                        logger.info(f"Reconnected for capture attempt {attempt + 1}")
                        time.sleep(0.3)  # Let camera stabilize after reconnect
                    except gp.GPhoto2Error as e:
                        last_error = e
                        logger.warning(f"Reconnect failed on attempt {attempt + 1}: {e}")
                        time.sleep(1)  # Wait before next reconnect attempt
                        continue
                
                try:
                    # Drain any pending camera events before capture
                    self._drain_camera_events()
                    
                    # Capture
                    file_path = self._camera.capture(gp.GP_CAPTURE_IMAGE)
                    logger.info(f"Captured: {file_path.folder}/{file_path.name}")
                    
                    # Wait for camera to finish writing (important for RAW files)
                    self._wait_for_camera_ready()
                    
                    # Download
                    camera_file = self._camera.file_get(
                        file_path.folder,
                        file_path.name,
                        gp.GP_FILE_TYPE_NORMAL
                    )
                    
                    # Determine extension and build filename: prefix_timestamp_suffix.ext
                    ext = Path(file_path.name).suffix or ".ARW"
                    suffix_part = f"_{suffix}" if suffix else ""
                    local_filename = f"{prefix}_{timestamp}{suffix_part}{ext}"
                    local_path = raw_path / local_filename
                    
                    # Save to raw/ subfolder
                    camera_file.save(str(local_path))
                    file_size = local_path.stat().st_size
                    logger.info(f"Saved: {local_path} ({file_size} bytes)")
                    
                    # Delete from camera
                    try:
                        self._camera.file_delete(file_path.folder, file_path.name)
                        logger.info(f"Deleted from camera: {file_path.name}")
                    except Exception as del_err:
                        logger.warning(f"Could not delete from camera: {del_err}")
                    
                    # Wait for camera to be ready for next operation
                    time.sleep(0.5)
                    self._drain_camera_events()
                    
                    # Post-process: generate TIFF, thumbnail, full_webview
                    processed = self._post_process_image(folder_path, local_filename, ext)
                    
                    event_bus.publish(EventType.CAPTURE_COMPLETE, {
                        "filename": local_filename,
                        "folder": folder,
                        "size": file_size
                    })
                    
                    return {
                        "success": True,
                        "filename": local_filename,
                        "filepath": str(local_path),
                        "file_url": f"/media/captures/{folder}/raw/{local_filename}",
                        "file_size": file_size,
                        "captured_at": datetime.now().isoformat(),
                        "thumbnail_url": processed.get("thumbnail_url"),
                        "webview_url": processed.get("webview_url"),
                        "tiff_url": processed.get("tiff_url"),
                    }
                
                except gp.GPhoto2Error as e:
                    last_error = e
                    logger.warning(f"Capture attempt {attempt + 1} failed: {e}")
                    self._cleanup_camera()
                    if attempt < max_retries - 1:
                        time.sleep(1.5)  # Wait longer before retry
            
            error_msg = f"Capture failed after {max_retries} attempts: {last_error}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
    
    def _post_process_image(self, folder_path: Path, raw_filename: str, ext: str) -> Dict[str, str]:
        """
        Post-process a captured RAW image:
        1. Convert RAW → 16-bit TIFF (saved to tiff/)
        2. Generate full web-view JPEG (saved to full_webview/)
        3. Generate small thumbnail JPEG (saved to thumbnail/)
        
        Returns dict with URLs for each derivative.
        Non-blocking: failures are logged but don't prevent capture success.
        """
        result = {}
        raw_path = folder_path / "raw" / raw_filename
        stem = Path(raw_filename).stem  # e.g. fabric_20260211_144925_top
        folder_name = folder_path.name
        
        # Create subdirectories
        tiff_dir = folder_path / "tiff"
        thumb_dir = folder_path / "thumbnail"
        webview_dir = folder_path / "full_webview"
        tiff_dir.mkdir(exist_ok=True)
        thumb_dir.mkdir(exist_ok=True)
        webview_dir.mkdir(exist_ok=True)
        
        try:
            import rawpy
            from PIL import Image as PILImage
            
            # Read RAW file
            with rawpy.imread(str(raw_path)) as raw:
                # ── 1. TIFF (16-bit, full resolution) ──
                try:
                    rgb_16 = raw.postprocess(
                        use_camera_wb=True,
                        output_bps=16,
                        no_auto_bright=True,
                        output_color=rawpy.ColorSpace.sRGB,
                        gamma=(1, 1),  # Linear output — gamma applied later by calibration
                    )
                    tiff_filename = f"{stem}.tiff"
                    tiff_path = tiff_dir / tiff_filename

                    # Try tifffile for proper 16-bit support, fallback to imageio/PIL
                    try:
                        import tifffile
                        tifffile.imwrite(str(tiff_path), rgb_16, compression='lzw')
                    except ImportError:
                        try:
                            import imageio.v3 as iio
                            iio.imwrite(str(tiff_path), rgb_16)
                        except ImportError:
                            # Fallback: save as 8-bit TIFF using PIL
                            rgb_8_tiff = (rgb_16 / 256).astype('uint8')
                            tiff_img = PILImage.fromarray(rgb_8_tiff)
                            tiff_img.save(str(tiff_path), format="TIFF", compression="tiff_lzw")
                            logger.info("Saved as 8-bit TIFF (install tifffile for 16-bit)")

                    result["tiff_url"] = f"/media/captures/{folder_name}/tiff/{tiff_filename}"
                    logger.info(f"TIFF saved: {tiff_path}")
                except Exception as e:
                    logger.warning(f"TIFF conversion failed: {e}", exc_info=True)
                
                # ── 2 & 3. Full webview + thumbnail (8-bit for JPEG) ──
                try:
                    rgb_8 = raw.postprocess(
                        use_camera_wb=True,
                        output_bps=8,
                        no_auto_bright=True,
                    )
                    full_img = PILImage.fromarray(rgb_8)
                    
                    # Full webview — resize to max 2400px on longest side, JPEG quality 92
                    webview_filename = f"{stem}.jpg"
                    webview_path = webview_dir / webview_filename
                    webview_img = full_img.copy()
                    webview_img.thumbnail((2400, 2400), PILImage.Resampling.LANCZOS)
                    webview_img.save(str(webview_path), format="JPEG", quality=92, optimize=True)
                    result["webview_url"] = f"/media/captures/{folder_name}/full_webview/{webview_filename}"
                    logger.info(f"Webview saved: {webview_path} ({webview_img.size[0]}x{webview_img.size[1]})")
                    
                    # Thumbnail — resize to max 400px, JPEG quality 80
                    thumb_filename = f"{stem}.jpg"
                    thumb_path = thumb_dir / thumb_filename
                    thumb_img = full_img.copy()
                    thumb_img.thumbnail((400, 400), PILImage.Resampling.LANCZOS)
                    thumb_img.save(str(thumb_path), format="JPEG", quality=80, optimize=True)
                    result["thumbnail_url"] = f"/media/captures/{folder_name}/thumbnail/{thumb_filename}"
                    logger.info(f"Thumbnail saved: {thumb_path} ({thumb_img.size[0]}x{thumb_img.size[1]})")
                    
                except Exception as e:
                    logger.warning(f"Webview/thumbnail generation failed: {e}")
                    
        except ImportError:
            logger.warning("rawpy/Pillow not installed — skipping post-processing. Install: pip install rawpy Pillow")
        except Exception as e:
            logger.warning(f"Post-processing failed for {raw_filename}: {e}")
        
        return result
    
    def _drain_camera_events(self, timeout_ms: int = 100):
        """Drain any pending camera events to clear the buffer"""
        if not self._camera or not self._context:
            return
        try:
            while True:
                event_type, event_data = self._camera.wait_for_event(timeout_ms)
                if event_type == gp.GP_EVENT_TIMEOUT:
                    break
                logger.debug(f"Drained event: {event_type}")
        except Exception as e:
            logger.debug(f"Event drain error (ok): {e}")
    
    def _wait_for_camera_ready(self, max_wait: float = 5.0):
        """Wait for camera to finish processing (e.g., after RAW capture)"""
        if not self._camera or not self._context:
            return
        
        start_time = time.time()
        while time.time() - start_time < max_wait:
            try:
                event_type, event_data = self._camera.wait_for_event(500)
                if event_type == gp.GP_EVENT_TIMEOUT:
                    # No more events, camera is idle
                    break
                elif event_type == gp.GP_EVENT_FILE_ADDED:
                    logger.debug(f"File added event: {event_data}")
                elif event_type == gp.GP_EVENT_CAPTURE_COMPLETE:
                    logger.debug("Capture complete event received")
                    break
            except Exception as e:
                logger.debug(f"Wait for ready error: {e}")
                break
        
        # Small extra delay for camera to fully stabilize
        time.sleep(0.2)
    
    # =========== Live View ===========
    
    def start_live_view(self) -> Generator[bytes, None, None]:
        """Start MJPEG live view stream"""
        # Stop any existing live view
        if self._live_view_active:
            self._stop_live_view.set()
            time.sleep(0.2)
        
        # Acquire lock just for setup
        with self._lock:
            if not self._connected or not self._camera:
                # Connect if needed
                self.kill_ptp_processes()
                time.sleep(0.3)
                try:
                    self._context = gp.Context()
                    self._camera = gp.Camera()
                    self._camera.init(self._context)
                    abilities = self._camera.get_abilities()
                    self._model = abilities.model
                    self._connected = True
                except Exception as e:
                    raise Exception(f"Failed to connect for live view: {e}")
            
            self._stop_live_view.clear()
            self._live_view_active = True
        
        # Generate frames (outside lock for performance)
        try:
            while not self._stop_live_view.is_set():
                try:
                    # Quick lock just for camera access
                    with self._lock:
                        if not self._camera or self._stop_live_view.is_set():
                            break
                        camera_file = self._camera.capture_preview()
                        data = bytes(camera_file.get_data_and_size())
                    
                    yield data
                    time.sleep(1.0 / settings.PREVIEW_FPS)
                    
                except gp.GPhoto2Error as e:
                    logger.error(f"Live view error: {e}")
                    break
                except Exception as e:
                    logger.error(f"Live view error: {e}")
                    break
        finally:
            self._live_view_active = False
            logger.info("Live view ended")
    
    def stop_live_view(self):
        """Stop live view stream"""
        self._stop_live_view.set()
        self._live_view_active = False


# Global singleton instance
camera_service = CameraService()

"""
Camera Service - Thread-safe singleton for Sony A7R III control via gphoto2
Simplified version with single lock and no keep-alive complexity
"""

import gphoto2 as gp
import subprocess
import time
import logging
import platform
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
        """Kill OS-specific processes that grab the camera USB.

        macOS: PTPCamera, ptpcamerad, mscamerad-xpc, cameracaptured
        Linux: gvfs-gphoto2-volume-monitor, gvfsd-gphoto2
        """
        if platform.system() == "Darwin":
            targets = settings.PTP_PROCESSES
        else:
            targets = settings.LINUX_USB_PROCESSES

        killed = []
        for proc in targets:
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
            logger.info(f"Killed USB-grabbing processes: {killed}")
            time.sleep(1.5)  # macOS respawns these fast — need enough delay

        return killed

    def reset_usb(self) -> bool:
        """Reset USB device via raw ioctl on Linux, gphoto2 --reset elsewhere.

        On Linux the USBDEVFS_RESET ioctl is used preferentially: it resets
        the port WITHOUT opening a PTP session. gphoto2 --reset loads the
        Sony PTP driver and claims the interface first — a port reset
        mid-handshake can wedge the camera's PTP responder (observed on
        A7R III running on mains power with no battery installed).
        """
        if platform.system() == "Linux":
            if self._usb_reset_ioctl():
                return True
            logger.warning(
                "ioctl USB reset failed; not falling back to gphoto2 --reset "
                "on Linux (PTP-session reset can wedge Sony bodies)"
            )
            return False

        try:
            result = subprocess.run(
                ["gphoto2", "--reset"],
                capture_output=True,
                text=True,
                timeout=10
            )
            logger.info(f"USB reset via gphoto2: {result.returncode == 0}")
            time.sleep(1)
            if result.returncode == 0:
                return True
        except Exception as e:
            logger.warning(f"gphoto2 reset failed: {e}")

        return False

    def _usb_reset_ioctl(self) -> bool:
        """Reset USB device via ioctl on Linux.

        Parses the bus/device from gphoto2 --auto-detect output
        (e.g. usb:001,004) and issues USBDEVFS_RESET on
        /dev/bus/usb/001/004.  Requires privileged container or
        appropriate permissions.
        """
        import fcntl

        try:
            info = self.detect_camera_info()
            port = info.get("port", "")  # e.g. "usb:001,004"
            if not port or not port.startswith("usb:"):
                logger.warning("Cannot determine USB bus/device for ioctl reset")
                return False

            bus_dev = port.replace("usb:", "").split(",")
            if len(bus_dev) != 2:
                logger.warning(f"Unexpected USB port format: {port}")
                return False

            dev_path = f"/dev/bus/usb/{bus_dev[0]}/{bus_dev[1]}"
            logger.info(f"Attempting ioctl USB reset on {dev_path}")

            USBDEVFS_RESET = 21780  # _IO('U', 20)
            with open(dev_path, "w") as fd:
                fcntl.ioctl(fd.fileno(), USBDEVFS_RESET, 0)

            logger.info(f"ioctl USB reset successful: {dev_path}")
            time.sleep(1)
            return True
        except PermissionError:
            logger.warning("ioctl USB reset failed: permission denied (container needs privileged mode)")
            return False
        except FileNotFoundError as e:
            logger.warning(f"ioctl USB reset failed: device node not found ({e})")
            return False
        except Exception as e:
            logger.warning(f"ioctl USB reset failed: {e}")
            return False
    
    def detect_camera(self) -> bool:
        """Check if camera is detected via gphoto2 CLI"""
        info = self.detect_camera_info()
        return info.get("detected", False)

    def detect_camera_info(self) -> Dict[str, Any]:
        """Detect camera and return detailed info (model, port, etc.)"""
        try:
            result = subprocess.run(
                ["gphoto2", "--auto-detect"],
                capture_output=True,
                text=True,
                timeout=10
            )
            output = result.stdout
            detected = "usb:" in output.lower()

            model = None
            port = None
            if detected:
                # Parse lines after the header separator
                for line in output.splitlines():
                    if "usb:" in line.lower():
                        # Format: "Sony ILCE-7RM3 (Control)    usb:001,004"
                        parts = line.rsplit("usb:", 1)
                        model = parts[0].strip() if parts[0].strip() else None
                        port = "usb:" + parts[1].strip() if len(parts) > 1 else None
                        break

            return {
                "detected": detected,
                "model": model,
                "port": port,
            }
        except Exception as e:
            logger.error(f"Camera detection failed: {e}")
            return {"detected": False, "model": None, "port": None, "error": str(e)}

    def startup_check(self) -> Dict[str, Any]:
        """Run at startup, return detection details for the startup banner"""
        self.kill_ptp_processes()
        info = self.detect_camera_info()
        if info["detected"]:
            logger.info(f"✓ Camera detected at startup: {info.get('model')} on {info.get('port')}")
        else:
            logger.warning("✗ No camera detected at startup")
        return info
    
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
            
            # Kill PTP grabbers with double-kill to beat macOS respawn
            self.kill_ptp_processes()
            time.sleep(1.0)
            self.kill_ptp_processes()  # kill the respawned ones
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
                    self._set_autofocus()
                    self._set_single_shot()

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
                        time.sleep(1.0)
                        self.kill_ptp_processes()
                        time.sleep(0.5)
            
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
            except Exception as e:
                logger.warning(f"Camera exit() failed (PTP session may remain open on camera): {e}")
            self._camera = None
            self._context = None
            # Let the kernel release the USB interface claim before any
            # subsequent operation touches the port.
            time.sleep(0.5)
        else:
            self._context = None
        self._connected = False
        self._model = None
    
    def _set_autofocus(self):
        """Set camera to autofocus mode"""
        try:
            config = self._camera.get_config(self._context)
            focus_widget = config.get_child_by_name("focusmode")
            focus_widget.set_value("Automatic")
            self._camera.set_config(config, self._context)
            logger.info("Set focus mode to Automatic")
        except Exception as e:
            logger.debug(f"Could not set autofocus: {e}")

    def _set_single_shot(self):
        """Ensure camera is in Single Shot mode (not bracket/burst)"""
        try:
            config = self._camera.get_config(self._context)
            mode_widget = config.get_child_by_name("capturemode")
            current = mode_widget.get_value()
            if current != "Single Shot":
                mode_widget.set_value("Single Shot")
                self._camera.set_config(config, self._context)
                logger.info(f"Set capture mode to Single Shot (was: {current})")
            else:
                logger.info("Capture mode already Single Shot")
        except Exception as e:
            logger.debug(f"Could not set single shot mode: {e}")
    
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
        """Kill USB-grabbing processes and recover the camera connection.

        USB port reset is a last resort: attempted only when the camera is
        NOT detected after process cleanup. Resetting the port on a healthy
        Sony body (especially mains-powered with no battery) can wedge its
        PTP responder until a full power cycle.
        """
        os_name = platform.system()  # "Darwin" or "Linux"
        with self._lock:
            self._stop_live_view.set()
            self._cleanup_camera()

            killed = self.kill_ptp_processes()
            time.sleep(0.3)

            camera_info = self.detect_camera_info()
            detected = camera_info.get("detected", False)

            usb_reset = False
            reset_skipped = detected
            if not detected:
                usb_reset = self.reset_usb()
                time.sleep(0.5)
                killed2 = self.kill_ptp_processes()
                killed.extend(killed2)
                time.sleep(0.3)
                camera_info = self.detect_camera_info()
                detected = camera_info.get("detected", False)

            parts = []
            parts.append(f"Platform: {os_name}.")
            if killed:
                parts.append(f"Killed {len(killed)} processes: {', '.join(killed)}.")
            else:
                parts.append("No USB-grabbing processes found to kill.")
            if usb_reset:
                parts.append("USB reset: success.")
            elif reset_skipped:
                parts.append("USB reset skipped — camera detected; port reset on a healthy Sony can wedge its PTP stack.")
            else:
                parts.append("USB reset: failed.")
            if detected:
                parts.append(f"Camera detected: {camera_info.get('model', 'unknown')} on {camera_info.get('port', 'unknown')}.")
            else:
                parts.append("Camera not detected after troubleshooting.")

            return {
                "success": True,
                "platform": os_name,
                "killed_processes": killed,
                "usb_reset": usb_reset,
                "camera_detected": detected,
                "camera_model": camera_info.get("model"),
                "camera_port": camera_info.get("port"),
                "message": " ".join(parts),
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
    
    def capture_image(self, folder: str, prefix: str = "capture", suffix: str = "", skip_post_process: bool = False) -> Dict[str, Any]:
        """Capture a single image and save to folder/raw/ subfolder.

        Args:
            folder: Capture session folder name
            prefix: Filename prefix (e.g., 'fabric')
            suffix: Suffix placed before extension (e.g., 'top', 'side_1')
            skip_post_process: If True, skip inline post-processing (for batch capture)
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
            
            # Generate filename: prefix_suffix.ext (dedup with (1), (2) if needed)
            
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
                    t0 = time.time()
                    file_path = self._camera.capture(gp.GP_CAPTURE_IMAGE)
                    t1 = time.time()
                    logger.info(f"Captured: {file_path.folder}/{file_path.name} ({t1-t0:.2f}s)")

                    # Wait for camera to finish writing (important for RAW files)
                    self._wait_for_camera_ready()
                    t2 = time.time()

                    # Download
                    camera_file = self._camera.file_get(
                        file_path.folder,
                        file_path.name,
                        gp.GP_FILE_TYPE_NORMAL
                    )
                    t3 = time.time()
                    logger.info(f"Timing: shutter={t1-t0:.2f}s wait={t2-t1:.2f}s download={t3-t2:.2f}s")
                    
                    # Determine extension and build filename: prefix_suffix.ext
                    ext = Path(file_path.name).suffix or ".ARW"
                    suffix_part = f"_{suffix}" if suffix else ""
                    base_name = f"{prefix}{suffix_part}"
                    local_filename = f"{base_name}{ext}"
                    local_path = raw_path / local_filename

                    # Only add (1), (2) etc. if filename already exists
                    counter = 1
                    while local_path.exists():
                        local_filename = f"{base_name}({counter}){ext}"
                        local_path = raw_path / local_filename
                        counter += 1
                    
                    # Save to raw/ subfolder
                    camera_file.save(str(local_path))
                    file_size = local_path.stat().st_size
                    logger.info(f"Saved: {local_path} ({file_size} bytes)")
                    
                    # Delete from camera SDRAM to free buffer
                    try:
                        self._camera.file_delete(file_path.folder, file_path.name)
                        logger.debug(f"Deleted from camera: {file_path.name}")
                    except Exception as del_err:
                        logger.warning(f"Could not delete from camera: {del_err}")
                    
                    # Post-process: generate TIFF, thumbnail, full_webview
                    processed = {}
                    if not skip_post_process:
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
                        "folder_path": str(folder_path),
                        "ext": ext,
                        "file_url": f"/media/captures/{folder}/raw/{local_filename}",
                        "file_size": file_size,
                        "captured_at": datetime.now().isoformat(),
                        "jpg_url": processed.get("jpg_url"),
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

    def capture_only(self) -> Dict[str, Any]:
        """Capture image to SD card without downloading.

        Triggers shutter, waits for camera ready, returns the camera-side
        file path.  Does NOT download, save locally, or delete from camera.
        Used for two-phase batch capture (capture all, then bulk download).
        """
        # Stop live view first (outside lock to avoid deadlock)
        if self._live_view_active:
            self._stop_live_view.set()
            for _ in range(30):
                if not self._live_view_active:
                    break
                time.sleep(0.1)
            time.sleep(0.5)

        with self._lock:
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
                        logger.info(f"Reconnected for capture_only attempt {attempt + 1}")
                        time.sleep(0.3)
                    except gp.GPhoto2Error as e:
                        last_error = e
                        logger.warning(f"Reconnect failed on attempt {attempt + 1}: {e}")
                        time.sleep(1)
                        continue

                try:
                    self._drain_camera_events()

                    t0 = time.time()
                    file_path = self._camera.capture(gp.GP_CAPTURE_IMAGE)
                    t1 = time.time()

                    # Wait for camera ready and capture SD card path from FILE_ADDED event.
                    # capture() returns a PTP buffer path (folder="/") which becomes
                    # inaccessible after subsequent captures.  The FILE_ADDED event
                    # carries the real SD card path that stays downloadable.
                    camera_folder = file_path.folder
                    camera_filename = file_path.name
                    start_wait = time.time()
                    while time.time() - start_wait < 10.0:
                        try:
                            event_type, event_data = self._camera.wait_for_event(500)
                            if event_type == gp.GP_EVENT_TIMEOUT:
                                break
                            elif event_type == gp.GP_EVENT_FILE_ADDED:
                                camera_folder = event_data.folder
                                camera_filename = event_data.name
                                logger.info(f"capture_only SD path: {camera_folder}/{camera_filename}")
                            elif event_type == gp.GP_EVENT_CAPTURE_COMPLETE:
                                break
                        except Exception as e:
                            logger.debug(f"capture_only wait error: {e}")
                            break

                    t2 = time.time()
                    logger.info(f"capture_only: {camera_folder}/{camera_filename} "
                                f"(shutter={t1-t0:.2f}s wait={t2-t1:.2f}s)")

                    return {
                        "success": True,
                        "camera_folder": camera_folder,
                        "camera_filename": camera_filename,
                    }

                except gp.GPhoto2Error as e:
                    last_error = e
                    logger.warning(f"capture_only attempt {attempt + 1} failed: {e}")
                    self._cleanup_camera()
                    if attempt < max_retries - 1:
                        time.sleep(1.5)

            error_msg = f"capture_only failed after {max_retries} attempts: {last_error}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

    def download_from_camera(self, camera_folder: str, camera_filename: str,
                             folder: str, prefix: str, suffix: str,
                             skip_post_process: bool = False) -> Dict[str, Any]:
        """Download a previously captured file from the camera SD card.

        Args:
            camera_folder: Camera-side folder path (from capture_only)
            camera_filename: Camera-side filename (from capture_only)
            folder: Local capture session folder name
            prefix: Filename prefix (e.g., 'batch')
            suffix: Suffix before extension (e.g., 'top', 'side_1')
            skip_post_process: If True, skip inline post-processing
        """
        with self._lock:
            if not self._connected or not self._camera:
                return {"success": False, "error": "Camera not connected"}

            folder_path = settings.CAPTURES_DIR / folder
            raw_path = folder_path / "raw"
            raw_path.mkdir(parents=True, exist_ok=True)

            try:
                t0 = time.time()
                camera_file = self._camera.file_get(
                    camera_folder,
                    camera_filename,
                    gp.GP_FILE_TYPE_NORMAL
                )
                t1 = time.time()

                ext = Path(camera_filename).suffix or ".ARW"
                suffix_part = f"_{suffix}" if suffix else ""
                base_name = f"{prefix}{suffix_part}"
                local_filename = f"{base_name}{ext}"
                local_path = raw_path / local_filename

                counter = 1
                while local_path.exists():
                    local_filename = f"{base_name}({counter}){ext}"
                    local_path = raw_path / local_filename
                    counter += 1

                camera_file.save(str(local_path))
                file_size = local_path.stat().st_size
                t2 = time.time()
                logger.info(f"Downloaded: {local_path} ({file_size} bytes, download={t1-t0:.2f}s save={t2-t1:.2f}s)")

                # Delete from camera
                try:
                    self._camera.file_delete(camera_folder, camera_filename)
                except Exception as del_err:
                    logger.warning(f"Could not delete from camera: {del_err}")

                # Post-process
                processed = {}
                if not skip_post_process:
                    processed = self._post_process_image(folder_path, local_filename, ext)

                return {
                    "success": True,
                    "filename": local_filename,
                    "filepath": str(local_path),
                    "folder_path": str(folder_path),
                    "ext": ext,
                    "file_url": f"/media/captures/{folder}/raw/{local_filename}",
                    "file_size": file_size,
                    "captured_at": datetime.now().isoformat(),
                    "jpg_url": processed.get("jpg_url"),
                }

            except gp.GPhoto2Error as e:
                error_msg = f"Download failed for {camera_folder}/{camera_filename}: {e}"
                logger.error(error_msg)
                return {"success": False, "error": error_msg}

    def trigger_autofocus(self) -> Dict[str, Any]:
        """Trigger autofocus on Sony A7R III.

        Uses gphoto2's 'autofocus' action toggle which maps to Sony's
        SetControlDeviceB PTP command internally.  Set value 1 to engage
        AF (equivalent to half-shutter press), hold 1.5s for the lens to
        lock, then set 2 to release.

        Drains pending PTP events first to ensure the camera session is
        clean (stale events after batch capture can block AF commands).
        """
        with self._lock:
            if not self._connected or not self._camera:
                return {"success": False, "error": "Camera not connected"}

            try:
                self._drain_camera_events(timeout_ms=50)
                config = self._camera.get_config(self._context)

                # Ensure AF mode
                focus_widget = config.get_child_by_name("focusmode")
                if focus_widget.get_value() != "Automatic":
                    focus_widget.set_value("Automatic")
                    self._camera.set_config(config, self._context)
                    logger.info("Switched to Automatic focus mode")
                    time.sleep(0.1)
                    config = self._camera.get_config(self._context)

                # Ensure AF toggle is released before engaging
                af_widget = config.get_child_by_name("autofocus")
                if af_widget.get_value() != 2:
                    af_widget.set_value(2)
                    self._camera.set_config(config, self._context)
                    time.sleep(0.1)
                    config = self._camera.get_config(self._context)

                # Engage AF (half-press)
                af_widget = config.get_child_by_name("autofocus")
                af_widget.set_value(1)
                self._camera.set_config(config, self._context)
                logger.info("AF engaged (value=1)")

                # Sony AF needs live-view sensor data to compute focus.
                # We hold the lock (blocking the live view thread), so we
                # must manually pump capture_preview() frames to give the
                # camera sensor input for AF processing.
                for _ in range(20):  # ~2s of preview frames
                    try:
                        self._camera.capture_preview()
                    except Exception:
                        pass
                    time.sleep(0.1)

                # Release (value=2)
                config = self._camera.get_config(self._context)
                af_widget = config.get_child_by_name("autofocus")
                af_widget.set_value(2)
                self._camera.set_config(config, self._context)
                logger.info("AF released (value=2)")

                return {"success": True, "message": "Autofocus triggered"}
            except Exception as e:
                logger.error(f"Autofocus failed: {e}")
                return {"success": False, "error": str(e)}

    def _post_process_image(self, folder_path: Path, raw_filename: str, ext: str) -> Dict[str, str]:
        """
        Post-process a captured RAW image:
        Decode RAW at 8-bit sRGB and save a single full-resolution JPG.
        Thumbnails/webviews are served on-the-fly via the resize endpoint.

        Returns dict with jpg_url.
        Non-blocking: failures are logged but don't prevent capture success.
        """
        result = {}
        raw_path = folder_path / "raw" / raw_filename
        stem = Path(raw_filename).stem  # e.g. fabric_20260211_144925_top
        folder_name = folder_path.name

        # Create jpg/ subdirectory
        jpg_dir = folder_path / "jpg"
        jpg_dir.mkdir(exist_ok=True)

        try:
            import rawpy
            from PIL import Image as PILImage

            with rawpy.imread(str(raw_path)) as raw:
                rgb_8 = raw.postprocess(
                    use_camera_wb=True,
                    output_bps=8,
                    no_auto_bright=True,
                    output_color=rawpy.ColorSpace.sRGB,
                )

            jpg_filename = f"{stem}.jpg"
            jpg_path = jpg_dir / jpg_filename
            img = PILImage.fromarray(rgb_8)
            img.save(str(jpg_path), format="JPEG", quality=95, optimize=True)
            result["jpg_url"] = f"/media/captures/{folder_name}/jpg/{jpg_filename}"
            logger.info(f"JPG saved: {jpg_path} ({img.size[0]}x{img.size[1]})")

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
    
    def _wait_for_camera_ready(self, max_wait: float = 10.0):
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

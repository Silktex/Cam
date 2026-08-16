"""
Camera Service - Thread-safe singleton for Sony A7R III control via gphoto2.

Non-blocking model: a single dedicated worker thread owns the ``gp.Camera``
object (libgphoto2 is single-session and NOT thread-safe), and interleaves two
kinds of work:

  1. Live-view frame production - polls ``capture_preview()`` at the configured
     FPS and publishes the latest frame into a ring buffer.
  2. Command execution - settings, capture, autofocus, etc. are queued and run
     between frames.

Because every camera operation is serialized on the worker thread, changing a
setting (e.g. shutter speed) while live view is streaming only pauses frame
production for the duration of the ``set_config`` transaction.  The stream
itself never tears down: the firmware may stall the preview object for 1-3s on
exposure changes, but the worker treats that as a transient error and retries
instead of killing the stream.  The HTTP consumer keeps yielding the last
frame, so the client freezes briefly and resumes - it does not disconnect.

The public API is unchanged.  ``self._lock`` is now a state/lifecycle lock that
guards ``_camera``/``_context``/``_connected``/``_model``; it is never held
during camera I/O.
"""

import gphoto2 as gp
import subprocess
import time
import logging
import platform
import threading
import atexit
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Generator
from threading import Lock, Event, Condition
from queue import Queue, Empty
from concurrent.futures import Future

from app.config import settings
from app.services.event_bus import event_bus, EventType

logger = logging.getLogger(__name__)

# Internal command tags dispatched by the worker thread.
_CMD_CONNECT = "connect"
_CMD_GET_SETTINGS = "get_settings"
_CMD_SET_SETTING = "set_setting"
_CMD_CAPTURE = "capture"
_CMD_CAPTURE_ONLY = "capture_only"
_CMD_DOWNLOAD = "download"
_CMD_AUTOFOCUS = "autofocus"
_CMD_SHUTDOWN = "shutdown"

_COMMAND_TIMEOUT_SECONDS = 30.0
_CONNECT_TIMEOUT_SECONDS = 120.0
_SHUTDOWN_TIMEOUT_SECONDS = 3.0


class CameraService:
    """Thread-safe singleton camera controller."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Camera state (guarded by _lock).
        self._camera = None
        self._context = None
        self._connected = False
        self._model = None

        # State/lifecycle lock.  NEVER held during camera I/O.
        self._lock = Lock()

        # Live view control.
        self._stop_live_view = Event()
        self._live_view_active = False
        self._live_view_generation = 0
        self._stream_source = "hdmi"  # "hdmi" | "ptp"

        # Worker thread + command queue.
        self._cmd_queue: Queue = Queue()
        self._stop_worker = Event()
        self._worker: Optional[threading.Thread] = None
        self._worker_start_lock = Lock()
        self._accepting_commands = True
        self._operation_cancel = Event()
        self._operation_submit_lock = Lock()
        self._cancel_callbacks = []

        # Frame ring buffer (latest-frame-wins).
        self._frame_cond = Condition()
        self._frame_seq = 0
        self._latest_frame: Optional[bytes] = None

        self._preview_fps = max(1, int(settings.PREVIEW_FPS))

        self._initialized = True

        # Register cleanup on exit
        atexit.register(self._cleanup_on_exit)

        logger.info("CameraService initialized (worker-thread non-blocking model)")

    # =====================================================================
    # Worker lifecycle
    # =====================================================================

    def _ensure_worker(self):
        """Start the worker thread if it isn't running."""
        with self._worker_start_lock:
            if not self._accepting_commands:
                raise RuntimeError("Camera worker is shutting down")
            if self._worker is None or not self._worker.is_alive():
                self._stop_worker.clear()
                self._worker = threading.Thread(
                    target=self._worker_loop,
                    name="camera-worker",
                    daemon=True,
                )
                self._worker.start()
                logger.info("Camera worker thread started")

    def _submit(self, tag: str, *args, **kwargs) -> Future:
        """Queue a command for the worker and return its result Future."""
        with self._worker_start_lock:
            if not self._accepting_commands:
                raise RuntimeError("Camera worker is shutting down")
            future: Future = Future()
            self._cmd_queue.put((tag, args, kwargs, future))
            return future

    def _worker_loop(self):
        """Single owner of the camera: interleaves commands and live view."""
        while not self._stop_worker.is_set():
            # Poll the command queue.  While live view is active we use a short
            # timeout so frames are produced at ~FPS; otherwise we idle cheaply.
            timeout = (1.0 / self._preview_fps) if self.live_view_active else 0.5
            try:
                item = self._cmd_queue.get(timeout=timeout)
            except Empty:
                item = None

            if item is None:
                self._maybe_produce_frame()
                continue

            tag, args, kwargs, future = item
            try:
                result = self._execute(tag, *args, **kwargs)
                future.set_result(result)
            except Exception as e:  # never let the worker die
                logger.exception(f"Worker command '{tag}' failed: {e}")
                if not future.done():
                    future.set_exception(e)
            if tag == _CMD_SHUTDOWN:
                return

    def _maybe_produce_frame(self):
        """Produce one live-view frame if streaming is requested and source is PTP."""
        if self._stream_source != "ptp" or not self.live_view_active or self._stop_live_view.is_set():
            return

        camera, _context = self._snapshot_camera()
        if camera is None or not self._connected:
            return

        try:
            camera_file = camera.capture_preview()
            data = bytes(camera_file.get_data_and_size())
        except gp.GPhoto2Error as e:
            # Transient during property changes / firmware stall.  Retry on the
            # next loop iteration instead of tearing down the stream.
            logger.debug(f"Live view transient error (retrying): {e}")
            return
        except Exception as e:
            logger.debug(f"Live view error (retrying): {e}")
            return

        with self._frame_cond:
            self._frame_seq += 1
            self._latest_frame = data
            self._frame_cond.notify_all()

    def _execute(self, tag: str, *args, **kwargs):
        if tag == _CMD_CONNECT:
            return self._do_connect()
        if tag == _CMD_GET_SETTINGS:
            return self._do_get_settings()
        if tag == _CMD_SET_SETTING:
            return self._do_set_setting(*args, **kwargs)
        if tag == _CMD_CAPTURE:
            return self._do_capture_image(*args, **kwargs)
        if tag == _CMD_CAPTURE_ONLY:
            return self._do_capture_only()
        if tag == _CMD_DOWNLOAD:
            return self._do_download(*args, **kwargs)
        if tag == _CMD_AUTOFOCUS:
            return self._do_autofocus()
        if tag == _CMD_SHUTDOWN:
            self._cleanup_camera()
            return None
        raise ValueError(f"Unknown command tag: {tag}")

    def _result(self, future: Future, timeout: float | None = None):
        return future.result(timeout=timeout or _COMMAND_TIMEOUT_SECONDS)

    def _fail_queued_commands(self) -> None:
        while True:
            try:
                _tag, _args, _kwargs, future = self._cmd_queue.get_nowait()
            except Empty:
                return
            if not future.done():
                future.set_exception(RuntimeError("Camera worker is shutting down"))

    def _shutdown_worker(self) -> bool:
        cleanup_without_worker = False
        with self._worker_start_lock:
            if not self._accepting_commands:
                worker = self._worker
                if worker is None:
                    return True
            else:
                worker = self._worker
            self._accepting_commands = False
            if worker is None:
                cleanup_without_worker = True
            else:
                self._fail_queued_commands()
                shutdown_future: Future = Future()
                self._cmd_queue.put((_CMD_SHUTDOWN, (), {}, shutdown_future))

        if cleanup_without_worker:
            if self.is_connected:
                self._ensure_worker_for_shutdown()
                return self._shutdown_worker()
            with self._worker_start_lock:
                self._accepting_commands = True
            return True

        worker.join(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        if worker.is_alive():
            return False
        self._worker = None
        with self._worker_start_lock:
            self._accepting_commands = True
        return True

    def _ensure_worker_for_shutdown(self) -> None:
        with self._worker_start_lock:
            self._stop_worker.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="camera-worker",
                daemon=True,
            )
            self._worker.start()

    def _snapshot_camera(self):
        """Return (camera, context) safely; never held during I/O."""
        with self._lock:
            return self._camera, self._context

    def _set_camera_state(self, camera, context, connected, model):
        with self._lock:
            self._camera = camera
            self._context = context
            self._connected = connected
            self._model = model

    def _install_cancel_callback(self, context) -> None:
        callback = context.set_cancel_func(
            lambda _context, _data: (
                gp.GP_CONTEXT_FEEDBACK_CANCEL
                if self._operation_cancel.is_set()
                else gp.GP_CONTEXT_FEEDBACK_OK
            ),
            None,
        )
        self._cancel_callbacks.append(callback)

    # =====================================================================
    # Process management (subprocess only - no worker needed)
    # =====================================================================

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

    # =====================================================================
    # Connection
    # =====================================================================

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected and self._camera is not None

    @property
    def model(self) -> Optional[str]:
        with self._lock:
            return self._model

    @property
    def live_view_active(self) -> bool:
        with self._frame_cond:
            return self._live_view_active

    def connect(self) -> Dict[str, Any]:
        """Connect to camera (runs on the worker thread)."""
        if self.is_connected:
            return {
                "success": True,
                "connected": True,
                "model": self.model,
                "message": "Already connected"
            }

        self._ensure_worker()
        try:
            return self._result(self._submit(_CMD_CONNECT), _CONNECT_TIMEOUT_SECONDS)
        except Exception as e:
            logger.error(f"Connect failed: {e}")
            return {
                "success": False,
                "connected": False,
                "model": None,
                "message": f"Failed to connect: {e}"
            }

    def _do_connect(self) -> Dict[str, Any]:
        # Kill PTP grabbers with double-kill to beat macOS respawn
        self.kill_ptp_processes()
        time.sleep(1.0)
        self.kill_ptp_processes()  # kill the respawned ones
        time.sleep(0.5)

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                logger.info(f"Connection attempt {attempt + 1}/{max_retries}")

                context = gp.Context()
                self._install_cancel_callback(context)
                camera = gp.Camera()
                camera.init(context)

                # Get camera model
                abilities = camera.get_abilities()
                model = abilities.model
                self._set_camera_state(camera, context, True, model)
                self._set_autofocus(camera, context)
                self._set_single_shot(camera, context)

                logger.info(f"✓ Connected to {model}")
                event_bus.publish(EventType.CAMERA_CONNECTED, {"model": model})

                return {
                    "success": True,
                    "connected": True,
                    "model": model,
                    "message": f"Connected to {model}"
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
        """Disconnect from camera (stops worker and live view)."""
        self.stop_live_view()

        stopped = self._shutdown_worker()
        if not stopped:
            return {
                "success": False,
                "connected": self.is_connected,
                "message": "Camera worker did not stop before the shutdown timeout",
            }
        event_bus.publish(EventType.CAMERA_DISCONNECTED, {})

        return {
            "success": True,
            "connected": False,
            "message": "Disconnected"
        }

    def _cleanup_camera(self):
        """Internal cleanup of camera resources."""
        with self._lock:
            camera = self._camera
            context = self._context
            self._camera = None
            self._context = None
            self._connected = False
            self._model = None
        if camera:
            try:
                camera.exit(context)
            except Exception:
                pass

    def _cleanup_on_exit(self):
        """Ensure camera is released on process exit"""
        logger.info("Cleaning up camera on exit...")
        self.stop_live_view()
        self._shutdown_worker()

    def _set_autofocus(self, camera, context):
        """Set camera to autofocus mode"""
        try:
            config = camera.get_config(context)
            focus_widget = config.get_child_by_name("focusmode")
            focus_widget.set_value("Automatic")
            camera.set_config(config, context)
            logger.info("Set focus mode to Automatic")
        except Exception as e:
            logger.debug(f"Could not set autofocus: {e}")

    def _set_single_shot(self, camera, context):
        """Ensure camera is in Single Shot mode (not bracket/burst)"""
        try:
            config = camera.get_config(context)
            mode_widget = config.get_child_by_name("capturemode")
            current = mode_widget.get_value()
            if current != "Single Shot":
                mode_widget.set_value("Single Shot")
                camera.set_config(config, context)
                logger.info(f"Set capture mode to Single Shot (was: {current})")
            else:
                logger.info("Capture mode already Single Shot")
        except Exception as e:
            logger.debug(f"Could not set single shot mode: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get camera status without locking"""
        detected = self.detect_camera()
        return {
            "connected": self.is_connected,
            "detected": detected,
            "model": self.model,
            "live_view_active": self.live_view_active
        }

    def troubleshoot(self) -> Dict[str, Any]:
        """Kill USB-grabbing processes, reset USB, and reconnect the camera.

        USB port reset is a last resort: attempted only when the camera is
        NOT detected after process cleanup. Resetting the port on a healthy
        Sony body (especially mains-powered with no battery) can wedge its
        PTP responder until a full power cycle.
        """
        os_name = platform.system()  # "Darwin" or "Linux"

        # Stop live view and the worker before touching the camera/USB.
        self.stop_live_view()
        if not self._shutdown_worker():
            return {
                "success": False,
                "platform": os_name,
                "killed_processes": [],
                "usb_reset": False,
                "camera_detected": self.is_connected,
                "camera_model": self.model,
                "camera_port": None,
                "message": "Camera worker did not stop before the shutdown timeout",
            }

        # Kill processes
        killed = self.kill_ptp_processes()
        time.sleep(0.3)

        # Do NOT reset the USB device: gphoto2 --reset / USBDEVFS_RESET wedge
        # the Sony A7R III PTP session so the camera stops answering commands
        # until it is power-cycled.  A clean disconnect + reconnect is the safe
        # recovery path for this camera.
        usb_reset = False

        # Kill again (daemons may respawn)
        killed2 = self.kill_ptp_processes()
        killed.extend(killed2)
        time.sleep(0.3)

        camera_info = self.detect_camera_info()
        detected = camera_info.get("detected", False)

        connected = False
        reconnect_msg = "Reconnect skipped."
        if detected:
            connect_result = self.connect()
            connected = connect_result.get("success", False)
            if connected:
                reconnect_msg = "Camera reconnected."
            else:
                reconnect_msg = f"Reconnect failed: {connect_result.get('message', 'unknown')}"

        parts = []
        parts.append(f"Platform: {os_name}.")
        if killed:
            parts.append(f"Killed {len(killed)} processes: {', '.join(killed)}.")
        else:
            parts.append("No USB-grabbing processes found to kill.")
        parts.append(f"USB reset: {'success' if usb_reset else 'failed'}.")
        if detected:
            parts.append(f"Camera detected: {camera_info.get('model', 'unknown')} on {camera_info.get('port', 'unknown')}.")
        else:
            parts.append("Camera not detected after troubleshooting.")
        parts.append(reconnect_msg)

        return {
            "success": True,
            "platform": os_name,
            "killed_processes": killed,
            "usb_reset": usb_reset,
            "camera_detected": detected,
            "camera_model": camera_info.get("model"),
            "camera_port": camera_info.get("port"),
            "connected": connected,
            "message": " ".join(parts),
        }

    # =====================================================================
    # Settings
    # =====================================================================

    def get_settings(self) -> List[Dict[str, Any]]:
        """Get camera settings (queued to worker; safe during live view)."""
        if not self.is_connected:
            return []

        self._ensure_worker()
        try:
            return self._result(self._submit(_CMD_GET_SETTINGS))
        except Exception as e:
            logger.warning(f"Failed to get settings: {e}")
            return []

    def _do_get_settings(self) -> List[Dict[str, Any]]:
        camera, context = self._snapshot_camera()
        if camera is None or not self._connected:
            return []
        try:
            config = camera.get_config(context)
            return self._parse_config(config)
        except gp.GPhoto2Error as e:
            logger.warning(f"Failed to get settings: {e}")
            return []

    def set_setting(self, name: str, value: Any) -> Dict[str, Any]:
        """Set a camera setting (non-blocking with respect to live view).

        The worker preempts preview for the duration of the ``set_config``
        transaction and resumes immediately after; the live view stream is
        never torn down.
        """
        if not self.is_connected:
            raise Exception("Camera not connected")

        self._ensure_worker()
        return self._result(self._submit(_CMD_SET_SETTING, name, value))

    def _do_set_setting(self, name: str, value: Any) -> Dict[str, Any]:
        camera, context = self._snapshot_camera()
        if camera is None or not self._connected:
            raise Exception("Camera not connected")

        try:
            config = camera.get_config(context)
            widget = config.get_child_by_name(name)

            # Type conversion based on widget type
            widget_type = widget.get_type()
            if widget_type == gp.GP_WIDGET_TOGGLE:
                value = int(bool(value))
            elif widget_type == gp.GP_WIDGET_RANGE:
                value = float(value)

            widget.set_value(value)
            camera.set_config(config, context)

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
            except Exception:
                item["value"] = None

            if widget_type in (gp.GP_WIDGET_RADIO, gp.GP_WIDGET_MENU):
                try:
                    item["choices"] = [widget.get_choice(i) for i in range(widget.count_choices())]
                except Exception:
                    item["choices"] = []

            if widget_type == gp.GP_WIDGET_RANGE:
                try:
                    item["range"] = widget.get_range()
                except Exception:
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

    # =====================================================================
    # Capture
    # =====================================================================

    def _stop_live_view_for_capture(self):
        """Stop live view and wait for the consumer to finish (outside worker)."""
        if self.live_view_active:
            self._stop_live_view.set()
            with self._frame_cond:
                self._frame_cond.notify_all()
            # Wait for live view to stop
            for _ in range(30):  # Wait up to 3 seconds
                if not self.live_view_active:
                    break
                time.sleep(0.1)
            time.sleep(0.5)  # Extra settle time after live view stops

    def capture_image(self, folder: str, prefix: str = "capture", suffix: str = "", skip_post_process: bool = False) -> Dict[str, Any]:
        """Capture a single image and save to folder/raw/ subfolder.

        Args:
            folder: Capture session folder name
            prefix: Filename prefix (e.g., 'fabric')
            suffix: Suffix placed before extension (e.g., 'top', 'side_1')
            skip_post_process: If True, skip inline post-processing (for batch capture)
        """
        self._stop_live_view_for_capture()

        self._ensure_worker()
        try:
            with self._operation_submit_lock:
                self._operation_cancel.clear()
                future = self._submit(_CMD_CAPTURE, folder, prefix, suffix, skip_post_process)
            return self._result(future)
        except Exception as e:
            logger.error(f"capture_image error: {e}")
            return {"success": False, "error": str(e)}

    def _do_capture_image(self, folder: str, prefix: str, suffix: str, skip_post_process: bool) -> Dict[str, Any]:
        # Create subfolder structure
        folder_path = settings.CAPTURES_DIR / folder
        raw_path = folder_path / "raw"
        raw_path.mkdir(parents=True, exist_ok=True)

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            if self._operation_cancel.is_set():
                return {"success": False, "error": "Capture cancelled"}
            camera, context = self._snapshot_camera()

            # Ensure connection before each attempt
            if not self._connected or camera is None:
                self.kill_ptp_processes()
                time.sleep(0.5)
                try:
                    context = gp.Context()
                    self._install_cancel_callback(context)
                    camera = gp.Camera()
                    camera.init(context)
                    model = camera.get_abilities().model
                    self._set_camera_state(camera, context, True, model)
                    logger.info(f"Reconnected for capture attempt {attempt + 1}")
                    time.sleep(0.3)  # Let camera stabilize after reconnect
                except gp.GPhoto2Error as e:
                    last_error = e
                    logger.warning(f"Reconnect failed on attempt {attempt + 1}: {e}")
                    time.sleep(1)  # Wait before next reconnect attempt
                    continue

            try:
                # Drain any pending camera events before capture
                self._drain_camera_events(camera, context)

                # Capture
                t0 = time.time()
                file_path = camera.capture(gp.GP_CAPTURE_IMAGE)
                t1 = time.time()
                logger.info(f"Captured: {file_path.folder}/{file_path.name} ({t1-t0:.2f}s)")

                # Wait for camera to finish writing (important for RAW files)
                self._wait_for_camera_ready(camera, context)
                t2 = time.time()

                # Download
                camera_file = camera.file_get(
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
                    camera.file_delete(file_path.folder, file_path.name)
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
        self._stop_live_view_for_capture()

        self._ensure_worker()
        try:
            with self._operation_submit_lock:
                self._operation_cancel.clear()
                future = self._submit(_CMD_CAPTURE_ONLY)
            return self._result(future)
        except Exception as e:
            logger.error(f"capture_only error: {e}")
            return {"success": False, "error": str(e)}

    def _do_capture_only(self) -> Dict[str, Any]:
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            if self._operation_cancel.is_set():
                return {"success": False, "error": "Capture cancelled"}
            camera, context = self._snapshot_camera()

            # Ensure connection before each attempt
            if not self._connected or camera is None:
                self.kill_ptp_processes()
                time.sleep(0.5)
                try:
                    context = gp.Context()
                    self._install_cancel_callback(context)
                    camera = gp.Camera()
                    camera.init(context)
                    model = camera.get_abilities().model
                    self._set_camera_state(camera, context, True, model)
                    logger.info(f"Reconnected for capture_only attempt {attempt + 1}")
                    time.sleep(0.3)
                except gp.GPhoto2Error as e:
                    last_error = e
                    logger.warning(f"Reconnect failed on attempt {attempt + 1}: {e}")
                    time.sleep(1)
                    continue

            try:
                self._drain_camera_events(camera, context)

                t0 = time.time()
                file_path = camera.capture(gp.GP_CAPTURE_IMAGE)
                t1 = time.time()

                # Wait for camera ready and capture SD card path from FILE_ADDED event.
                # capture() returns a PTP buffer path (folder="/") which becomes
                # inaccessible after subsequent captures.  The FILE_ADDED event
                # carries the real SD card path that stays downloadable.
                camera_folder = file_path.folder
                camera_filename = file_path.name
                start_wait = time.time()
                while time.time() - start_wait < 10.0:
                    if self._operation_cancel.is_set():
                        return {"success": False, "error": "Capture cancelled"}
                    try:
                        event_type, event_data = camera.wait_for_event(500)
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
        if not self.is_connected:
            return {"success": False, "error": "Camera not connected"}

        self._ensure_worker()
        try:
            return self._result(self._submit(
                _CMD_DOWNLOAD, camera_folder, camera_filename, folder,
                prefix, suffix, skip_post_process
            ))
        except Exception as e:
            logger.error(f"download_from_camera error: {e}")
            return {"success": False, "error": str(e)}

    def _do_download(self, camera_folder: str, camera_filename: str,
                     folder: str, prefix: str, suffix: str,
                     skip_post_process: bool) -> Dict[str, Any]:
        camera, context = self._snapshot_camera()
        if camera is None or not self._connected:
            return {"success": False, "error": "Camera not connected"}

        folder_path = settings.CAPTURES_DIR / folder
        raw_path = folder_path / "raw"
        raw_path.mkdir(parents=True, exist_ok=True)

        try:
            t0 = time.time()
            camera_file = camera.file_get(
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
                camera.file_delete(camera_folder, camera_filename)
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
        if not self.is_connected:
            return {"success": False, "error": "Camera not connected"}

        self._ensure_worker()
        try:
            return self._result(self._submit(_CMD_AUTOFOCUS))
        except Exception as e:
            logger.error(f"Autofocus failed: {e}")
            return {"success": False, "error": str(e)}

    def _do_autofocus(self) -> Dict[str, Any]:
        camera, context = self._snapshot_camera()
        if camera is None or not self._connected:
            return {"success": False, "error": "Camera not connected"}

        try:
            self._drain_camera_events(camera, context, timeout_ms=50)
            config = camera.get_config(context)

            # Ensure AF mode
            focus_widget = config.get_child_by_name("focusmode")
            if focus_widget.get_value() != "Automatic":
                focus_widget.set_value("Automatic")
                camera.set_config(config, context)
                logger.info("Switched to Automatic focus mode")
                time.sleep(0.1)
                config = camera.get_config(context)

            # Ensure AF toggle is released before engaging
            af_widget = config.get_child_by_name("autofocus")
            if af_widget.get_value() != 2:
                af_widget.set_value(2)
                camera.set_config(config, context)
                time.sleep(0.1)
                config = camera.get_config(context)

            # Engage AF (half-press)
            af_widget = config.get_child_by_name("autofocus")
            af_widget.set_value(1)
            camera.set_config(config, context)
            logger.info("AF engaged (value=1)")

            # Sony AF needs live-view sensor data to compute focus.
            # We run on the worker thread (which is the live-view producer),
            # so manually pump capture_preview() frames to give the camera
            # sensor input for AF processing.
            for _ in range(20):  # ~2s of preview frames
                try:
                    camera.capture_preview()
                except Exception:
                    pass
                time.sleep(0.1)

            # Release (value=2)
            config = camera.get_config(context)
            af_widget = config.get_child_by_name("autofocus")
            af_widget.set_value(2)
            camera.set_config(config, context)
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

    def _drain_camera_events(self, camera, context, timeout_ms: int = 100):
        """Drain any pending camera events to clear the buffer"""
        if camera is None or context is None:
            return
        try:
            while True:
                event_type, event_data = camera.wait_for_event(timeout_ms)
                if event_type == gp.GP_EVENT_TIMEOUT:
                    break
                logger.debug(f"Drained event: {event_type}")
        except Exception as e:
            logger.debug(f"Event drain error (ok): {e}")

    def _wait_for_camera_ready(self, camera, context, max_wait: float = 10.0):
        """Wait for camera to finish processing (e.g., after RAW capture)"""
        if camera is None or context is None:
            return

        start_time = time.time()
        while time.time() - start_time < max_wait:
            try:
                event_type, event_data = camera.wait_for_event(500)
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

    # =====================================================================
    # Live View
    # =====================================================================

    def start_live_view(self) -> Generator[bytes, None, None]:
        """Start MJPEG live view stream.

        The worker thread produces frames into a ring buffer; this generator
        consumes the latest frame.  Because production and consumption are
        decoupled, a settings change (which pauses production briefly) does
        not tear down the stream - the generator simply waits and the client
        keeps showing the last frame.
        """
        # Ensure connected (connect if needed)
        if not self.is_connected:
            result = self.connect()
            if not result.get("success"):
                raise Exception(f"Failed to connect for live view: {result.get('message')}")

        self._ensure_worker()

        with self._frame_cond:
            self._live_view_generation += 1
            generation = self._live_view_generation
            self._stop_live_view.clear()
            self._live_view_active = True
            self._latest_frame = None
            last_seq = self._frame_seq
            self._frame_cond.notify_all()
        try:
            while True:
                with self._frame_cond:
                    self._frame_cond.wait_for(
                        lambda: (
                            self._frame_seq != last_seq
                            or generation != self._live_view_generation
                            or self._stop_live_view.is_set()
                        ),
                        timeout=1.0,
                    )
                    if (
                        generation != self._live_view_generation
                        or self._stop_live_view.is_set()
                    ):
                        break
                    last_seq = self._frame_seq
                    data = self._latest_frame

                if data is not None:
                    yield data
        finally:
            with self._frame_cond:
                if generation == self._live_view_generation:
                    self._live_view_active = False
                self._frame_cond.notify_all()
            logger.info("Live view ended")

    def stop_live_view(self):
        """Stop live view stream"""
        with self._frame_cond:
            self._stop_live_view.set()
            self._live_view_generation += 1
            self._live_view_active = False
            self._frame_cond.notify_all()

    @property
    def stream_source(self) -> str:
        """Active live view stream source ('hdmi' | 'ptp')."""
        return self._stream_source

    def set_stream_source(self, source: str) -> str:
        """Switch active live view stream source ('hdmi' | 'ptp')."""
        source_normalized = source.lower().strip()
        if source_normalized not in ("hdmi", "ptp"):
            raise ValueError(f"Invalid stream source: {source}. Must be 'hdmi' or 'ptp'.")
        self._stream_source = source_normalized
        logger.info(f"Live view stream source set to: {self._stream_source}")
        return self._stream_source

    def request_operation_cancel(self) -> None:
        with self._operation_submit_lock:
            self._operation_cancel.set()


# Global singleton instance
camera_service = CameraService()

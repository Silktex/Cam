"""
Video Device Discovery and Capabilities Service
Queries V4L2 devices, detects MacroSilicon USB 3.0 HDMI Capture Card, and returns hardware encoding capabilities.
"""
import glob
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MACROSILICON_NAMES = ["USB3. 0 capture", "MacroSilicon", "USB Video"]


class VideoDeviceService:
    """Service to discover and query video capture devices."""

    def __init__(self):
        self._cached_devices: Optional[List[Dict[str, Any]]] = None

    def get_devices(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """Enumerate video capture devices in /sys/class/video4linux/."""
        if self._cached_devices is not None and not refresh:
            return self._cached_devices

        devices = []
        video_paths = sorted(glob.glob("/sys/class/video4linux/video*"))

        for path in video_paths:
            dev_node = f"/dev/{os.path.basename(path)}"
            name_file = os.path.join(path, "name")
            name = "Unknown Video Device"
            if os.path.exists(name_file):
                try:
                    with open(name_file, "r") as f:
                        name = f.read().strip()
                except Exception as e:
                    logger.debug(f"Failed to read device name from {name_file}: {e}")

            # Normalize device name for MacroSilicon HDMI Capture Card
            friendly_name = name
            is_macrosilicon = False
            for marker in MACROSILICON_NAMES:
                if marker.lower() in name.lower():
                    friendly_name = "MacroSilicon USB 3.0 HDMI Capture Card"
                    is_macrosilicon = True
                    break

            device_info: Dict[str, Any] = {
                "device_node": dev_node,
                "sysfs_path": path,
                "raw_name": name,
                "name": friendly_name,
                "is_capture_card": is_macrosilicon,
                "formats": self._query_formats_for_device(dev_node, is_macrosilicon),
                "hw_accel": {
                    "enabled": True,
                    "encoder": "h264_vaapi (AMD Radeon Vega 11)",
                    "device": "/dev/dri/renderD128",
                    "profile": "constrained_baseline",
                },
                "stream_endpoints": {
                    "rtsp": "rtsp://127.0.0.1:8554/stream",
                    "whep": "/stream/whep",
                    "hls": "/hls/stream/index.m3u8",
                },
            }
            devices.append(device_info)

        self._cached_devices = devices
        return devices

    def get_primary_capture_card(self) -> Optional[Dict[str, Any]]:
        """Return the primary MacroSilicon HDMI capture card, or first video device."""
        devices = self.get_devices()
        for dev in devices:
            if dev.get("is_capture_card"):
                return dev
        return devices[0] if devices else None

    def _query_formats_for_device(self, dev_node: str, is_macrosilicon: bool) -> List[Dict[str, Any]]:
        """Query supported video formats and resolutions via v4l2-ctl or standard fallback matrix."""
        # Try dynamic v4l2-ctl query if available
        formats = self._query_v4l2_ctl(dev_node)
        if formats:
            return formats

        # Fallback profile for MacroSilicon USB 3.0 HDMI Capture Card
        if is_macrosilicon:
            return [
                {
                    "pixel_format": "MJPG",
                    "description": "Motion-JPEG",
                    "resolutions": [
                        {"width": 1920, "height": 1080, "fps": [60, 30, 25, 20, 10], "default": True},
                        {"width": 1600, "height": 1200, "fps": [60, 30, 25, 20, 10]},
                        {"width": 1280, "height": 720, "fps": [60, 50, 30, 20, 10]},
                        {"width": 1024, "height": 768, "fps": [60, 50, 30, 20, 10]},
                    ],
                },
                {
                    "pixel_format": "YUYV",
                    "description": "YUYV 4:2:2 Raw",
                    "resolutions": [
                        {"width": 1920, "height": 1080, "fps": [5]},
                        {"width": 1280, "height": 720, "fps": [10]},
                        {"width": 640, "height": 480, "fps": [30, 20, 10]},
                    ],
                },
            ]

        return [
            {
                "pixel_format": "MJPG",
                "description": "Motion-JPEG",
                "resolutions": [
                    {"width": 1920, "height": 1080, "fps": [30], "default": True},
                    {"width": 1280, "height": 720, "fps": [30]},
                ],
            }
        ]

    def _query_v4l2_ctl(self, dev_node: str) -> Optional[List[Dict[str, Any]]]:
        """Execute v4l2-ctl to query formats if installed."""
        try:
            res = subprocess.run(
                ["v4l2-ctl", "--list-formats-ext", "-d", dev_node],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode != 0 or not res.stdout:
                return None

            formats = []
            current_format: Optional[Dict[str, Any]] = None
            current_res: Optional[Dict[str, Any]] = None

            for line in res.stdout.splitlines():
                line_str = line.strip()
                if line_str.startswith("[") and "]:" in line_str:
                    # New format line, e.g. [0]: 'MJPG' (Motion-JPEG, compressed)
                    parts = line_str.split(":", 1)
                    if len(parts) == 2:
                        fmt_info = parts[1].strip()
                        fmt_code = fmt_info.split("'")[1] if "'" in fmt_info else fmt_info[:4]
                        current_format = {
                            "pixel_format": fmt_code,
                            "description": fmt_info,
                            "resolutions": [],
                        }
                        formats.append(current_format)
                elif line_str.startswith("Size: Discrete") and current_format is not None:
                    # Size line, e.g. Size: Discrete 1920x1080
                    size_str = line_str.replace("Size: Discrete", "").strip()
                    if "x" in size_str:
                        w_str, h_str = size_str.split("x")
                        try:
                            w, h = int(w_str), int(h_str)
                            current_res = {"width": w, "height": h, "fps": []}
                            current_format["resolutions"].append(current_res)
                        except ValueError:
                            pass
                elif line_str.startswith("Interval: Discrete") and current_res is not None:
                    # Interval line, e.g. Interval: Discrete 0.033s (30.000 fps)
                    if "(" in line_str and "fps)" in line_str:
                        fps_part = line_str.split("(")[1].split("fps")[0].strip()
                        try:
                            fps_val = int(float(fps_part))
                            if fps_val not in current_res["fps"]:
                                current_res["fps"].append(fps_val)
                        except ValueError:
                            pass

            return formats if formats else None
        except Exception as e:
            logger.debug(f"v4l2-ctl query failed for {dev_node}: {e}")
            return None


video_device_service = VideoDeviceService()

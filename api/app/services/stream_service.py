"""RTSP live stream pipeline manager.

Owns an ffmpeg VA-API publisher that encodes /dev/video0 (UVC preview from the
camera) to H.264 and pushes it to mediamtx over RTSP. mediamtx then fans the
stream out to any number of viewers via HLS / WebRTC / RTSP.

The publisher is supervised: if ffmpeg exits unexpectedly (camera unplugged
mid-stream, device hiccup) it is relaunched with exponential backoff until
explicitly stopped.
"""
import logging
import subprocess
import threading
import time

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)


class StreamService:
    def __init__(self):
        self._proc = None
        self._desired = False
        self._supervisor = None
        self._lock = threading.Lock()

    @property
    def rtsp_url(self) -> str:
        return f"rtsp://{settings.MEDIAMTX_HOST}:{settings.MEDIAMTX_RTSP_PORT}/{settings.STREAM_PATH}"

    @property
    def hls_base_url(self) -> str:
        return f"http://{settings.MEDIAMTX_HOST}:{settings.MEDIAMTX_HLS_PORT}"

    def _ffmpeg_cmd(self):
        bitrate = f"{settings.STREAM_BITRATE_KBPS}k"
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-vaapi_device", settings.STREAM_VAAPI_DEVICE,
            "-f", "v4l2", "-input_format", "mjpeg",
            "-video_size", settings.STREAM_RESOLUTION,
            "-framerate", str(settings.STREAM_FPS),
            "-i", settings.STREAM_VIDEO_DEVICE,
            "-vf", "format=nv12,hwupload",
            "-c:v", "h264_vaapi",
            "-profile:v", "constrained_baseline",
            "-level", "4.0", "-bf", "0",
            "-rc_mode", "CBR",
            "-b:v", bitrate, "-maxrate", bitrate,
            "-bufsize", f"{settings.STREAM_BITRATE_KBPS * 2}k",
            "-g", "40",
            "-f", "rtsp", "-rtsp_transport", "tcp",
            self.rtsp_url,
        ]

    def _run(self):
        backoff = 2.0
        while self._desired:
            cmd = self._ffmpeg_cmd()
            logger.info("Starting ffmpeg publisher: %s", " ".join(cmd))
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                logger.error("ffmpeg not found on PATH; stream publisher unavailable")
                self._proc = None
                return
            rc = self._proc.wait()
            self._proc = None
            if not self._desired:
                return
            logger.warning("ffmpeg exited rc=%s; relaunching in %.0fs", rc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def _publisher_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def hls_available(self) -> bool:
        url = f"{self.hls_base_url}/{settings.STREAM_PATH}/index.m3u8"
        timeout = aiohttp.ClientTimeout(total=4, connect=2)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def start(self) -> dict:
        if self._desired and self._publisher_alive():
            return {"started": True, "message": "publisher already running", "external": False}

        if await self.hls_available():
            return {"started": True, "message": "external publisher active; serving HLS", "external": True}

        with self._lock:
            self._desired = True
            if not (self._supervisor and self._supervisor.is_alive()):
                self._supervisor = threading.Thread(target=self._run, daemon=True)
                self._supervisor.start()

        return {"started": True, "message": "starting publisher", "external": False}

    def stop(self) -> dict:
        with self._lock:
            self._desired = False
            proc = self._proc
            self._proc = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        return {"started": False, "message": "stopped"}

    async def status(self) -> dict:
        hls_ok = await self.hls_available()
        return {
            "desired": self._desired,
            "publisher_alive": self._publisher_alive(),
            "hls_available": hls_ok,
            "stream_path": settings.STREAM_PATH,
            "rtsp_url": self.rtsp_url,
            "hls_playlist_url": f"/api/stream/hls/{settings.STREAM_PATH}/index.m3u8",
        }


stream_service = StreamService()

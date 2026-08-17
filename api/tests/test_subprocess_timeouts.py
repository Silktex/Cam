"""
Characterization + timeout-bound tests for the subprocess.run call sites in
camera_service (gphoto2 / killall) and video_device_service (v4l2-ctl).

Bounded call sites (plan production-hardening todo 7):
  - camera_service.kill_ptp_processes     killall -9              timeout=5s
  - camera_service.reset_usb              gphoto2 --reset         timeout=30s
  - camera_service.detect_camera_info     gphoto2 --auto-detect   timeout=30s
  - video_device_service._query_v4l2_ctl  v4l2-ctl probe          timeout=10s

Timeout value justification (mirrored in service code comments):
  - gphoto2 CLI probes normally finish in ~1-3s, but a wedged USB bus can
    hang them indefinitely; 30s is generous vs slow-but-healthy USB
    enumeration (and matches the worker's 30s command budget) while
    guaranteeing startup/health flows can never block forever.
  - killall -9 only delivers SIGKILL (no graceful wait to run out), so 5s
    is already a generous bound; it only trips if killall itself hangs.
  - v4l2-ctl format enumeration normally completes in well under a second,
    but a wedged USB capture card can hang the ioctl chain; 10s bounds the
    probe per device and callers fall back to the static format matrix.

DOCUMENTED EXEMPTION: stream_service.py's subprocess.Popen (ffmpeg RTSP
publisher) is intentionally NOT bounded here — it is a long-lived streaming
process supervised by its own restart loop, not a request/response probe.

TDD order: the characterization tests below pin current success-path
behavior (including exact command arguments) and were verified green
against the PRE-change code; the timeout-bound and timeout-path tests were
RED against pre-change code (values were 10s/10s/2s and timeouts were
swallowed by broad `except Exception` without typed handling) and drive the
implementation.
"""
import logging
import subprocess
import time

import pytest

from app.services import camera_service as camera_module
from app.services.camera_service import camera_service
from app.services.video_device_service import VideoDeviceService


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _completed(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class _HangingSubprocess:
    """Fake subprocess.run simulating a child that hangs past its deadline.

    The real subprocess.run raises TimeoutExpired itself once ``timeout``
    elapses; this stub reproduces that raise after a tiny wall delay so
    tests can assert the SERVICE returns promptly (<5s wall) on timeout
    instead of hanging — without paying a real 10-30s wait per test.
    """

    def __init__(self, hang_seconds=0.2):
        self.hang_seconds = hang_seconds
        self.calls = []  # (cmd list, kwargs) per invocation

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append((list(cmd), kwargs))
        time.sleep(self.hang_seconds)
        raise subprocess.TimeoutExpired(
            cmd=list(cmd), timeout=kwargs.get("timeout")
        )


@pytest.fixture
def darwin(monkeypatch):
    """Route camera_service down its non-Linux (gphoto2 CLI) branches."""
    monkeypatch.setattr(camera_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(camera_module.settings, "PTP_PROCESSES", ["FakePTPDaemon"])


@pytest.fixture
def no_sleep(monkeypatch):
    """Neutralize the by-design settle sleeps in kill_ptp/reset_usb."""
    monkeypatch.setattr(camera_module.time, "sleep", lambda *_a, **_k: None)


# ──────────────────────────────────────────────
# Characterization: success paths (pin pre-change behavior)
# ──────────────────────────────────────────────

def test_kill_ptp_processes_success_returns_killed_list(monkeypatch, darwin, no_sleep):
    """kill_ptp_processes returns the list of daemons killed with rc=0."""
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = list(cmd)
        recorded["kwargs"] = kwargs
        return _completed(rc=0)

    monkeypatch.setattr(camera_module.subprocess, "run", fake_run)
    killed = camera_service.kill_ptp_processes()

    assert killed == ["FakePTPDaemon"]
    # Command arguments are part of the pinned contract (must not change).
    assert recorded["cmd"] == ["killall", "-9", "FakePTPDaemon"]


def test_reset_usb_gphoto2_success_and_rc_failure(monkeypatch, darwin, no_sleep):
    """reset_usb (non-Linux path): rc=0 -> True, rc!=0 -> False."""
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = list(cmd)
        recorded["kwargs"] = kwargs
        return _completed(rc=recorded.get("rc", 0))

    monkeypatch.setattr(camera_module.subprocess, "run", fake_run)

    recorded["rc"] = 0
    assert camera_service.reset_usb() is True

    recorded["rc"] = 1
    assert camera_service.reset_usb() is False

    assert recorded["cmd"] == ["gphoto2", "--reset"]


AUTO_DETECT_STDOUT = (
    "Model                          Port\n"
    "----------------------------------------------------------\n"
    "Sony ILCE-7RM3 (Control)      usb:001,004\n"
)


def test_detect_camera_info_parses_auto_detect_output(monkeypatch):
    """detect_camera_info parses model/port from gphoto2 --auto-detect."""
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = list(cmd)
        recorded["kwargs"] = kwargs
        return _completed(rc=0, stdout=AUTO_DETECT_STDOUT)

    monkeypatch.setattr(camera_module.subprocess, "run", fake_run)
    info = camera_service.detect_camera_info()

    assert info["detected"] is True
    assert info["model"] == "Sony ILCE-7RM3 (Control)"
    assert info["port"] == "usb:001,004"
    assert recorded["cmd"] == ["gphoto2", "--auto-detect"]


def test_detect_camera_info_no_usb_reports_not_detected(monkeypatch):
    """No 'usb:' in output -> detected False with null model/port."""

    def fake_run(cmd, **kwargs):
        return _completed(rc=0, stdout="Model                          Port\n")

    monkeypatch.setattr(camera_module.subprocess, "run", fake_run)
    info = camera_service.detect_camera_info()

    assert info["detected"] is False
    assert info["model"] is None
    assert info["port"] is None


V4L2_STDOUT = (
    "ioctl: VIDIOC_ENUM_FMT\n"
    "\tType: Video Capture\n"
    "\n"
    "\t[0]: 'MJPG' (Motion-JPEG, compressed)\n"
    "\t\tSize: Discrete 1920x1080\n"
    "\t\t\tInterval: Discrete 0.033s (30.000 fps)\n"
    "\t\t\tInterval: Discrete 0.017s (60.000 fps)\n"
    "\t[1]: 'YUYV' (YUYV 4:2:2, uncompressed)\n"
    "\t\tSize: Discrete 1280x720\n"
    "\t\t\tInterval: Discrete 0.100s (10.000 fps)\n"
)


def test_query_v4l2_ctl_parses_formats_output(monkeypatch):
    """_query_v4l2_ctl parses formats/resolutions/fps from v4l2-ctl output."""
    service = VideoDeviceService()
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = list(cmd)
        recorded["kwargs"] = kwargs
        return _completed(rc=0, stdout=V4L2_STDOUT)

    monkeypatch.setattr(
        "app.services.video_device_service.subprocess.run", fake_run
    )
    formats = service._query_v4l2_ctl("/dev/video0")

    assert formats is not None
    assert formats[0]["pixel_format"] == "MJPG"
    assert formats[0]["resolutions"][0] == {
        "width": 1920, "height": 1080, "fps": [30, 60]
    }
    assert formats[1]["pixel_format"] == "YUYV"
    assert recorded["cmd"] == [
        "v4l2-ctl", "--list-formats-ext", "-d", "/dev/video0"
    ]


def test_query_v4l2_ctl_nonzero_rc_returns_none(monkeypatch):
    """v4l2-ctl rc!=0 -> None so callers fall back to the static matrix."""
    service = VideoDeviceService()

    def fake_run(cmd, **kwargs):
        return _completed(rc=1, stdout="")

    monkeypatch.setattr(
        "app.services.video_device_service.subprocess.run", fake_run
    )
    assert service._query_v4l2_ctl("/dev/video0") is None


# ──────────────────────────────────────────────
# Timeout bounds (failing-first: 30s gphoto2 / 10s v4l2 / 5s killall)
# ──────────────────────────────────────────────

def test_gphoto2_calls_bounded_to_30_seconds(monkeypatch, darwin, no_sleep):
    """Both gphoto2 subprocess calls must pass timeout=30.

    Justification: gphoto2 probes normally take ~1-3s but a wedged USB bus
    hangs them forever; 30s matches the worker's command budget while
    bounding startup/health flows. (Pre-change value was 10s.)
    """
    hanging = _HangingSubprocess(hang_seconds=0.0)
    monkeypatch.setattr(camera_module.subprocess, "run", hanging)

    camera_service.detect_camera_info()
    camera_service.reset_usb()

    timeouts = [kwargs.get("timeout") for _, kwargs in hanging.calls]
    assert timeouts == [30, 30]


def test_v4l2_probe_bounded_to_10_seconds(monkeypatch):
    """v4l2-ctl probe must pass timeout=10 (pre-change value was 2s).

    Justification: enumeration is sub-second when healthy; a wedged capture
    card hangs ioctls — 10s bounds the per-device probe and the caller
    falls back to the static format matrix on expiry.
    """
    service = VideoDeviceService()
    hanging = _HangingSubprocess(hang_seconds=0.0)
    monkeypatch.setattr(
        "app.services.video_device_service.subprocess.run", hanging
    )

    service._query_v4l2_ctl("/dev/video0")

    assert hanging.calls[0][1].get("timeout") == 10


def test_killall_keeps_5_second_bound(monkeypatch, darwin, no_sleep):
    """killall -9 keeps its 5s bound: SIGKILL delivery is near-instant, so
    5s is already generous; only a hung killall itself trips it."""
    hanging = _HangingSubprocess(hang_seconds=0.0)
    monkeypatch.setattr(camera_module.subprocess, "run", hanging)

    camera_service.kill_ptp_processes()

    assert hanging.calls[0][1].get("timeout") == 5


# ──────────────────────────────────────────────
# Timeout paths: existing error shapes, returned promptly (<5s wall)
# ──────────────────────────────────────────────

def test_detect_camera_info_timeout_returns_error_dict_quickly(
    monkeypatch, caplog
):
    """Timeout -> existing not-detected error dict, well under 5s wall.

    Error contract (pinned): {"detected": False, "model": None,
    "port": None, "error": <str mentioning the timeout>}.
    """
    monkeypatch.setattr(
        camera_module.subprocess, "run", _HangingSubprocess(hang_seconds=0.2)
    )
    with caplog.at_level(logging.ERROR, logger="app.services.camera_service"):
        start = time.perf_counter()
        info = camera_service.detect_camera_info()
        elapsed = time.perf_counter() - start

    assert info["detected"] is False
    assert info["model"] is None
    assert info["port"] is None
    assert "timed out" in info["error"]
    assert elapsed < 5.0, f"returned in {elapsed:.2f}s; must not hang"
    # Typed handling must log an explicit detection-timeout record.
    assert "detection timed out" in caplog.text


def test_kill_ptp_processes_timeout_skips_hung_daemon(
    monkeypatch, darwin, no_sleep, caplog
):
    """Timeout on one daemon skips it and keeps killing the rest.

    Error contract (pinned): returns the partial killed-list; a hung
    killall must not abort the loop.
    """

    def fake_run(cmd, **kwargs):
        if "FakePTPDaemon" in cmd:
            time.sleep(0.2)
            raise subprocess.TimeoutExpired(cmd=list(cmd), timeout=kwargs.get("timeout"))
        return _completed(rc=0)

    monkeypatch.setattr(camera_module.settings, "PTP_PROCESSES",
                        ["FakePTPDaemon", "FakeOtherDaemon"])
    monkeypatch.setattr(camera_module.subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING, logger="app.services.camera_service"):
        start = time.perf_counter()
        killed = camera_service.kill_ptp_processes()
        elapsed = time.perf_counter() - start

    assert killed == ["FakeOtherDaemon"]
    assert elapsed < 5.0, f"returned in {elapsed:.2f}s; must not hang"
    assert "timed out" in caplog.text


def test_reset_usb_timeout_returns_false_quickly(
    monkeypatch, darwin, no_sleep, caplog
):
    """Timeout on gphoto2 --reset -> existing False contract, <5s wall."""
    monkeypatch.setattr(
        camera_module.subprocess, "run", _HangingSubprocess(hang_seconds=0.2)
    )
    with caplog.at_level(logging.WARNING, logger="app.services.camera_service"):
        start = time.perf_counter()
        result = camera_service.reset_usb()
        elapsed = time.perf_counter() - start

    assert result is False
    assert elapsed < 5.0, f"returned in {elapsed:.2f}s; must not hang"
    assert "reset timed out" in caplog.text


def test_v4l2_probe_timeout_returns_none_and_falls_back(monkeypatch, caplog):
    """Timeout on v4l2-ctl -> None, caller serves fallback format matrix."""
    service = VideoDeviceService()
    hanging = _HangingSubprocess(hang_seconds=0.2)
    monkeypatch.setattr(
        "app.services.video_device_service.subprocess.run", hanging
    )

    with caplog.at_level(logging.DEBUG, logger="app.services.video_device_service"):
        start = time.perf_counter()
        result = service._query_v4l2_ctl("/dev/video0")
        formats = service._query_formats_for_device("/dev/video0", True)
        elapsed = time.perf_counter() - start

    assert result is None
    assert elapsed < 5.0, f"returned in {elapsed:.2f}s; must not hang"
    # Fallback matrix for the MacroSilicon capture card is served.
    fallback_formats = [f["pixel_format"] for f in formats]
    assert "MJPG" in fallback_formats and "YUYV" in fallback_formats
    assert "timed out after 10s" in caplog.text

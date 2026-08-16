import threading
from concurrent.futures import Future

import pytest

from app.services import camera_service as camera_module
from app.services.batch_capture_service import BatchCaptureService
from app.services.camera_service import CameraService


class RecordingCamera:
    def __init__(self) -> None:
        self.exit_thread: str | None = None

    def exit(self, _context) -> None:
        self.exit_thread = threading.current_thread().name


class CancelContext:
    def __init__(self) -> None:
        self.callback = None
        self.callback_data = None

    def set_cancel_func(self, callback, callback_data):
        self.callback = callback
        self.callback_data = callback_data
        return callback


class StuckWorker:
    def __init__(self) -> None:
        self.joined = threading.Event()

    def is_alive(self) -> bool:
        return True

    def join(self, timeout: float | None = None) -> None:
        assert timeout is not None
        self.joined.set()


@pytest.fixture
def camera_service(monkeypatch: pytest.MonkeyPatch) -> CameraService:
    monkeypatch.setattr(CameraService, "_instance", None)
    monkeypatch.setattr(CameraService, "_initialized", False)
    service = CameraService()
    monkeypatch.setattr(camera_module, "_COMMAND_TIMEOUT_SECONDS", 0.05, raising=False)
    monkeypatch.setattr(camera_module, "_SHUTDOWN_TIMEOUT_SECONDS", 0.05, raising=False)
    return service


def wait_for_live_view(service: CameraService, expected: bool) -> None:
    with service._frame_cond:
        assert service._frame_cond.wait_for(
            lambda: service._live_view_active is expected,
            timeout=1.0,
        )


def test_disconnect_preserves_stuck_worker_without_external_camera_exit(
    camera_service: CameraService,
) -> None:
    camera = RecordingCamera()
    worker = StuckWorker()
    camera_service._set_camera_state(camera, object(), True, "fake")
    camera_service._worker = worker

    result = camera_service.disconnect()

    assert result["success"] is False
    assert camera_service._worker is worker
    assert camera.exit_thread is None
    assert worker.joined.is_set()


def test_disconnect_runs_camera_exit_on_worker_thread(
    camera_service: CameraService,
) -> None:
    camera = RecordingCamera()
    camera_service._set_camera_state(camera, object(), True, "fake")

    result = camera_service.disconnect()

    assert result["success"] is True
    assert camera.exit_thread == "camera-worker"
    assert camera_service._worker is None


def test_disconnect_immediately_clears_live_view_state(
    camera_service: CameraService,
) -> None:
    camera = RecordingCamera()
    camera_service._set_camera_state(camera, object(), True, "fake")
    with camera_service._frame_cond:
        camera_service._live_view_active = True

    result = camera_service.disconnect()

    assert result["success"] is True
    assert camera_service.live_view_active is False


def test_shutdown_rejects_submissions_and_fails_queued_futures(
    camera_service: CameraService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocking_execute(_tag: str, *_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=1.0)
        return {"success": True}

    monkeypatch.setattr(camera_service, "_execute", blocking_execute)
    camera_service._ensure_worker()
    active = camera_service._submit("active")
    assert entered.wait(timeout=1.0)
    queued = camera_service._submit("queued")

    result = camera_service.disconnect()

    assert result["success"] is False
    with pytest.raises(RuntimeError, match="shutting down"):
        queued.result(timeout=0)
    with pytest.raises(RuntimeError, match="shutting down"):
        camera_service._submit("late")
    release.set()
    assert active.result(timeout=1.0) == {"success": True}


def test_public_command_wait_is_bounded(
    camera_service: CameraService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera_service._set_camera_state(RecordingCamera(), object(), True, "fake")
    monkeypatch.setattr(camera_service, "_ensure_worker", lambda: None)
    unresolved: Future = Future()
    monkeypatch.setattr(camera_service, "_submit", lambda *_args, **_kwargs: unresolved)

    with pytest.raises(TimeoutError):
        camera_service.set_setting("iso", "100")


def test_context_cancel_callback_tracks_operation_cancel(
    camera_service: CameraService,
) -> None:
    context = CancelContext()

    camera_service._install_cancel_callback(context)
    assert context.callback is not None
    assert context.callback(context, context.callback_data) == camera_module.gp.GP_CONTEXT_FEEDBACK_OK

    camera_service.request_operation_cancel()

    assert context.callback(context, context.callback_data) == camera_module.gp.GP_CONTEXT_FEEDBACK_CANCEL


def test_capture_submission_and_cancel_do_not_lose_cancel_request(
    camera_service: CameraService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera_service._set_camera_state(RecordingCamera(), object(), True, "fake")
    submitted = threading.Event()
    release_submit = threading.Event()
    unresolved: Future = Future()

    def submit(*_args, **_kwargs):
        submitted.set()
        assert release_submit.wait(timeout=1.0)
        return unresolved

    monkeypatch.setattr(camera_service, "_ensure_worker", lambda: None)
    monkeypatch.setattr(camera_service, "_submit", submit)
    capture = threading.Thread(
        target=camera_service.capture_image,
        args=("test",),
    )
    capture.start()
    assert submitted.wait(timeout=1.0)

    cancelled = threading.Event()
    cancel = threading.Thread(
        target=lambda: (camera_service.request_operation_cancel(), cancelled.set()),
    )
    cancel.start()
    assert not cancelled.wait(timeout=0.05)
    release_submit.set()
    unresolved.set_result({"success": False, "error": "Capture cancelled"})
    capture.join(timeout=1.0)
    cancel.join(timeout=1.0)

    assert cancelled.is_set()
    assert camera_service._operation_cancel.is_set()


def test_troubleshoot_reconnects_without_destructive_usb_reset(
    camera_service: CameraService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(camera_module.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(camera_service, "kill_ptp_processes", lambda: [])
    reset_calls: list[int] = []
    monkeypatch.setattr(
        camera_service,
        "reset_usb",
        lambda: reset_calls.append(1) or True,
    )
    monkeypatch.setattr(
        camera_service,
        "detect_camera_info",
        lambda: {"detected": True, "model": "fake", "port": "usb:001,001"},
    )
    connect_calls: list[int] = []
    monkeypatch.setattr(
        camera_service,
        "connect",
        lambda: connect_calls.append(1)
        or {
            "success": True,
            "connected": True,
            "model": "fake",
            "message": "Connected to fake",
        },
    )

    result = camera_service.troubleshoot()

    assert result["connected"] is True
    assert "reconnected" in result["message"].lower()
    assert connect_calls == [1]
    assert reset_calls == []


def test_new_live_view_owner_replaces_old_without_stale_frame(
    camera_service: CameraService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera_service._set_camera_state(RecordingCamera(), object(), True, "fake")
    monkeypatch.setattr(camera_service, "_ensure_worker", lambda: None)
    with camera_service._frame_cond:
        camera_service._frame_seq = 1
        camera_service._latest_frame = b"stale"

    first = camera_service.start_live_view()
    second = camera_service.start_live_view()
    first_result: list[bytes | type[StopIteration]] = []
    second_result: list[bytes | type[StopIteration]] = []

    def consume(generator, result) -> None:
        try:
            result.append(next(generator))
        except StopIteration:
            result.append(StopIteration)

    first_thread = threading.Thread(target=consume, args=(first, first_result))
    first_thread.start()
    wait_for_live_view(camera_service, True)
    second_thread = threading.Thread(target=consume, args=(second, second_result))
    second_thread.start()

    with camera_service._frame_cond:
        assert camera_service._frame_cond.wait_for(
            lambda: camera_service._live_view_generation >= 2,
            timeout=1.0,
        )
        camera_service._frame_seq += 1
        camera_service._latest_frame = b"fresh"
        camera_service._frame_cond.notify_all()

    first_thread.join(timeout=1.0)
    second_thread.join(timeout=1.0)
    assert first_result == [StopIteration]
    assert second_result == [b"fresh"]


def test_stop_live_view_immediately_wakes_consumer_and_reports_inactive(
    camera_service: CameraService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera_service._set_camera_state(RecordingCamera(), object(), True, "fake")
    monkeypatch.setattr(camera_service, "_ensure_worker", lambda: None)
    stream = camera_service.start_live_view()
    result: list[type[StopIteration]] = []

    def consume() -> None:
        try:
            next(stream)
        except StopIteration:
            result.append(StopIteration)

    consumer = threading.Thread(target=consume)
    consumer.start()
    wait_for_live_view(camera_service, True)

    camera_service.stop_live_view()

    assert camera_service._live_view_active is False
    consumer.join(timeout=1.0)
    assert result == [StopIteration]


@pytest.mark.asyncio
async def test_batch_cancel_requests_cooperative_worker_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = BatchCaptureService()
    service._state.is_running = True
    requested = threading.Event()
    monkeypatch.setattr(
        camera_module.camera_service,
        "request_operation_cancel",
        requested.set,
        raising=False,
    )
    monkeypatch.setattr(
        camera_module.camera_service,
        "_cleanup_camera",
        lambda: pytest.fail("cancel must not clean up the camera from the event-loop thread"),
    )

    result = await service.cancel()

    assert result == {"success": True, "message": "Cancellation requested"}
    assert requested.is_set()

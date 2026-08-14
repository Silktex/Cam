import asyncio
import threading

import pytest

from app.services.event_bus import EventBus, EventType
from main import app, lifespan


class RecordingWebSocket:
    def __init__(self, sent: asyncio.Event) -> None:
        self.sent = sent
        self.messages: list[str] = []
        self.send_thread: str | None = None

    async def send_text(self, message: str) -> None:
        self.messages.append(message)
        self.send_thread = threading.current_thread().name
        self.sent.set()


class ClosingLoop:
    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, *_args) -> None:
        raise RuntimeError("Event loop is closed")


@pytest.mark.asyncio
async def test_worker_publish_schedules_websocket_send_on_attached_loop() -> None:
    EventBus._instance = None
    bus = EventBus()
    sent = asyncio.Event()
    websocket = RecordingWebSocket(sent)
    callback_thread: list[str] = []
    bus.attach_loop(asyncio.get_running_loop())
    bus.register_ws(websocket)
    bus.subscribe(
        EventType.SETTING_CHANGED,
        lambda _event_type, _data: callback_thread.append(threading.current_thread().name),
    )

    publisher = threading.Thread(
        name="camera-worker",
        target=bus.publish,
        args=(EventType.SETTING_CHANGED, {"name": "iso", "value": "100"}),
    )
    publisher.start()
    publisher.join(timeout=1.0)
    await asyncio.wait_for(sent.wait(), timeout=1.0)

    assert callback_thread == ["camera-worker"]
    assert websocket.send_thread == threading.current_thread().name
    assert '"type": "setting_changed"' in websocket.messages[0]


def test_publish_does_not_fail_when_loop_closes_during_scheduling() -> None:
    EventBus._instance = None
    bus = EventBus()
    bus.attach_loop(ClosingLoop())
    bus.register_ws(object())

    bus.publish(EventType.CAMERA_DISCONNECTED, {})


@pytest.mark.asyncio
async def test_lifespan_attaches_and_detaches_application_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attached: list[asyncio.AbstractEventLoop] = []
    detached: list[asyncio.AbstractEventLoop] = []
    monkeypatch.setattr("main.event_bus.attach_loop", attached.append)
    monkeypatch.setattr("main.event_bus.detach_loop", detached.append)
    monkeypatch.setattr("main.camera_service.startup_check", lambda: {"detected": False})
    monkeypatch.setattr("main.camera_service.disconnect", lambda: {"success": True})

    async def connect_light():
        return {"host": "test", "connected": False}

    async def disconnect_light() -> None:
        return None

    monkeypatch.setattr("main.light_service.connect", connect_light)
    monkeypatch.setattr("main.light_service.disconnect", disconnect_light)

    async with lifespan(app):
        assert attached == [asyncio.get_running_loop()]
    assert detached == attached

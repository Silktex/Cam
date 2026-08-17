"""
ESP32 Light Controller Service
Manages real-time connection to ESP32 (ESPHome) via Server-Sent Events (SSE)
stream for sub-millisecond status push, HTTP commands for light control,
and broadcasts state changes instantly via WebSocket to all connected UI clients.
"""
import asyncio
import json
import logging
from typing import Dict, List, Optional, Set
from urllib.parse import quote
import aiohttp
from fastapi import WebSocket

from app.config import settings
from app.models.light import LightState

logger = logging.getLogger(__name__)


class LightControllerService:
    """Manages ESP32 SSE streaming connection, light states, and WebSocket broadcasts."""

    def __init__(self):
        self.lights: Dict[int, LightState] = {}
        self.connected: bool = False
        self._cmd_session: Optional[aiohttp.ClientSession] = None
        self._sse_session: Optional[aiohttp.ClientSession] = None
        self._sse_task: Optional[asyncio.Task] = None
        self._websocket_clients: Set[WebSocket] = set()
        self._broadcast_lock = asyncio.Lock()
        
        # Initialize light states from config
        names = settings.light_names_list
        pins = settings.light_pins_list
        
        for i in range(len(names)):
            self.lights[i] = LightState(
                id=i,
                name=names[i],
                pin=pins[i],
                on=False,
                brightness=100
            )

    async def connect(self) -> dict:
        """Initialize sessions and start background SSE stream listener.

        Returns dict with connection details for startup reporting.
        """
        host = settings.ESP32_HOST
        result = {"host": host, "connected": False, "lights": len(self.lights)}
        try:
            if not self._cmd_session or self._cmd_session.closed:
                self._cmd_session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5)
                )

            # Test connection by checking ESP32 root
            async with self._cmd_session.get(f"http://{host}/") as resp:
                if resp.status == 200:
                    self.connected = True
                    result["connected"] = True
                    logger.info(f"Connected to ESP32 at {host}")
                else:
                    self.connected = False
                    result["http_status"] = resp.status
                    logger.warning(f"ESP32 returned status {resp.status}")

            # Start persistent real-time SSE listener
            self._start_sse_listener()

            # Broadcast initial state
            await self._broadcast_state()
            return result

        except Exception as e:
            logger.warning(f"Could not connect to ESP32: {e}")
            logger.info("Running in simulation mode - states tracked locally")
            self.connected = False
            result["error"] = str(e)
            self._start_sse_listener()  # Will keep attempting reconnect in background
            return result

    def _start_sse_listener(self):
        """Start background SSE streaming task."""
        if self._sse_task is None or self._sse_task.done():
            self._sse_task = asyncio.create_task(self._sse_listener_loop())
            logger.info("Started ESP32 SSE real-time listener task")

    def _stop_sse_listener(self):
        """Stop background SSE streaming task."""
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            self._sse_task = None
            logger.info("Stopped ESP32 SSE listener task")

    def _get_light_index(self, payload: dict) -> Optional[int]:
        """Map an ESPHome entity payload to our internal light index."""
        name_id = payload.get("name_id", "")  # e.g. "light/Top Light"
        entity_id = payload.get("id", "")      # e.g. "light-top_light"
        raw_name = payload.get("name", "")     # e.g. "Top Light"
        
        # Clean name from name_id if needed
        clean_name = raw_name or (name_id.split("/", 1)[1] if "/" in name_id else name_id)
        clean_name_lower = clean_name.lower().strip()
        
        names = settings.light_names_list
        for idx, n in enumerate(names):
            if n.lower().strip() == clean_name_lower:
                return idx
            # Match slugified names (e.g. "light-top_light" -> "top light")
            slug = n.lower().strip().replace(" ", "_")
            if entity_id in (f"light-{slug}", slug, f"light_{slug}"):
                return idx
                
        return None

    def _handle_sse_payload(self, payload: dict):
        """Process state event received from ESP32 SSE stream."""
        idx = self._get_light_index(payload)
        if idx is None or idx not in self.lights:
            return

        state_val = str(payload.get("state", payload.get("value", "OFF"))).upper()
        new_on = (state_val == "ON")
        
        brightness_raw = payload.get("brightness")
        if brightness_raw is not None:
            try:
                # ESPHome brightness is 0-255
                b_val = float(brightness_raw)
                new_brightness = max(0, min(100, int(round(b_val * 100 / 255))))
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"Invalid brightness payload {brightness_raw!r} for light {idx}; "
                    f"keeping previous brightness: {e}"
                )
                new_brightness = self.lights[idx].brightness
        else:
            new_brightness = self.lights[idx].brightness

        # Check if state changed
        if self.lights[idx].on != new_on or self.lights[idx].brightness != new_brightness:
            self.lights[idx].on = new_on
            self.lights[idx].brightness = new_brightness
            logger.info(f"[SSE PUSH] {self.lights[idx].name}: {'ON' if new_on else 'OFF'} @ {new_brightness}%")
            # Schedule immediate broadcast to WebSocket clients
            asyncio.create_task(self._broadcast_state())

    async def _sse_listener_loop(self):
        """Persistent SSE streaming connection to ESPHome."""
        host = settings.ESP32_HOST
        events_url = f"http://{host}/events"
        headers = {"Accept": "text/event-stream"}
        stream_timeout = aiohttp.ClientTimeout(total=None, connect=5, sock_read=None)

        while True:
            try:
                if not self._sse_session or self._sse_session.closed:
                    self._sse_session = aiohttp.ClientSession(timeout=stream_timeout)

                async with self._sse_session.get(events_url, headers=headers) as resp:
                    if resp.status == 200:
                        if not self.connected:
                            self.connected = True
                            logger.info(f"Connected to ESP32 SSE stream at {host}")
                            await self._broadcast_state()

                        current_event = ""
                        while True:
                            line = await resp.content.readline()
                            if not line:
                                break  # Stream ended / disconnected
                            text = line.decode("utf-8", errors="ignore").strip()
                            if text.startswith("event:"):
                                current_event = text.split(":", 1)[1].strip()
                            elif text.startswith("data:"):
                                data_str = text[5:].strip()
                                if not data_str:
                                    continue
                                try:
                                    payload = json.loads(data_str)
                                    if current_event == "state" or "state" in payload or "value" in payload:
                                        self._handle_sse_payload(payload)
                                except Exception as e:
                                    # Keep-alive noise / partial frames must not
                                    # kill the SSE listener loop.
                                    logger.debug(
                                        f"Ignoring malformed ESP32 SSE event "
                                        f"({current_event!r}): {data_str[:100]!r}: {e}"
                                    )
                            elif not text:
                                current_event = ""
                    else:
                        logger.debug(f"ESP32 SSE endpoint returned HTTP {resp.status}")
                        if self.connected:
                            self.connected = False
                            await self._broadcast_state()

            except asyncio.CancelledError:
                logger.info("ESP32 SSE listener task cancelled")
                break
            except Exception as e:
                if self.connected:
                    logger.warning(f"ESP32 SSE stream disconnected: {e}")
                    self.connected = False
                    await self._broadcast_state()
                logger.debug(f"Retrying SSE stream connection in 3s: {e}")

            # Reconnection backoff
            try:
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                break

    async def _send_light_command(self, light_name: str, on: bool, brightness: Optional[int] = None) -> bool:
        """Send HTTP command to ESP32."""
        if not self._cmd_session or self._cmd_session.closed:
            self._cmd_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            )

        try:
            encoded_name = quote(light_name)
            
            if on:
                url = f"http://{settings.ESP32_HOST}/light/{encoded_name}/turn_on"
                if brightness is not None:
                    # Convert 0-100% to 0-255
                    esp_brightness = int(round(brightness * 255 / 100))
                    url += f"?brightness={esp_brightness}"
            else:
                url = f"http://{settings.ESP32_HOST}/light/{encoded_name}/turn_off"
            
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            async with self._cmd_session.post(url, headers=headers) as resp:
                if resp.status == 200:
                    logger.info(f"[ESP32 CMD] {light_name}: {'ON' if on else 'OFF'}" + 
                               (f" @ {brightness}%" if brightness and on else ""))
                    return True
                else:
                    logger.error(f"ESP32 returned {resp.status} for {light_name}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to send command to ESP32: {e}")
            return False

    async def set_light(self, light_id: int, on: bool, brightness: Optional[int] = None) -> LightState:
        """Turn a light on/off and optionally set brightness."""
        if light_id < 0 or light_id >= len(self.lights):
            raise ValueError(f"Invalid light ID: {light_id}")

        self.lights[light_id].on = on
        if brightness is not None:
            self.lights[light_id].brightness = max(0, min(100, brightness))

        # Optimistically broadcast immediate state change to UI
        await self._broadcast_state()

        if self.connected:
            names = settings.light_names_list
            success = await self._send_light_command(
                names[light_id],
                on,
                self.lights[light_id].brightness if on else None
            )
            if not success:
                logger.warning("Command failed, state tracked locally")
        else:
            names = settings.light_names_list
            logger.info(f"[SIM] {names[light_id]}: {'ON' if on else 'OFF'} @ {self.lights[light_id].brightness}%")
        
        return self.lights[light_id]

    async def set_all_lights(self, on: bool, brightness: Optional[int] = None) -> List[LightState]:
        """Control all lights at once."""
        results = []
        for i in range(len(self.lights)):
            result = await self.set_light(i, on, brightness)
            results.append(result)
        return results

    def get_all_states(self) -> List[LightState]:
        """Get current state of all lights."""
        return list(self.lights.values())

    def get_health(self) -> dict:
        """Get health status."""
        return {
            "status": "ok" if self.connected else "degraded",
            "connected": self.connected,
            "host": settings.ESP32_HOST,
            "port": 80,
            "total_lights": len(self.lights),
            "protocol": "esphome_sse",
            "message": "Connected to ESP32 via ESPHome SSE" if self.connected else "Running in simulation mode"
        }

    async def disconnect(self):
        """Close HTTP sessions and stop SSE stream."""
        self._stop_sse_listener()
        if self._cmd_session and not self._cmd_session.closed:
            await self._cmd_session.close()
            self._cmd_session = None
        if self._sse_session and not self._sse_session.closed:
            await self._sse_session.close()
            self._sse_session = None
        self.connected = False
        logger.info("Disconnected from ESP32")

    # ─── WebSocket Management ───────────────────────────────────────

    async def register_websocket(self, websocket: WebSocket):
        """Register a new WebSocket client and send initial state."""
        async with self._broadcast_lock:
            self._websocket_clients.add(websocket)
            logger.info(f"WebSocket client connected. Total: {len(self._websocket_clients)}")
        
        # Send initial state immediately
        await self._send_to_client(websocket, {
            "type": "state_update",
            "data": {
                "lights": [light.model_dump() for light in self.get_all_states()],
                "connected": self.connected,
                "host": settings.ESP32_HOST
            }
        })

    async def unregister_websocket(self, websocket: WebSocket):
        """Unregister a WebSocket client."""
        async with self._broadcast_lock:
            self._websocket_clients.discard(websocket)
            logger.info(f"WebSocket client disconnected. Total: {len(self._websocket_clients)}")

    async def _send_to_client(self, websocket: WebSocket, message: dict):
        """Send a message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send to WebSocket client: {e}")
            await self.unregister_websocket(websocket)

    async def _broadcast_state(self):
        """Broadcast current state to all connected WebSocket clients."""
        if not self._websocket_clients:
            return

        message = {
            "type": "state_update",
            "data": {
                "lights": [light.model_dump() for light in self.get_all_states()],
                "connected": self.connected,
                "host": settings.ESP32_HOST
            }
        }

        async with self._broadcast_lock:
            dead_clients = set()
            for client in self._websocket_clients:
                try:
                    await client.send_json(message)
                except Exception as e:
                    # Send failure is the dead-client detection signal itself.
                    logger.debug(f"Dropping unresponsive light-state WebSocket client: {e}")
                    dead_clients.add(client)

            # Remove dead clients
            self._websocket_clients -= dead_clients

    async def broadcast_health(self):
        """Broadcast health status to all connected WebSocket clients."""
        if not self._websocket_clients:
            return

        message = {
            "type": "health",
            "data": self.get_health()
        }

        async with self._broadcast_lock:
            dead_clients = set()
            for client in self._websocket_clients:
                try:
                    await client.send_json(message)
                except Exception as e:
                    logger.debug(f"Dropping unresponsive light-health WebSocket client: {e}")
                    dead_clients.add(client)

            self._websocket_clients -= dead_clients


# Singleton instance
light_service = LightControllerService()

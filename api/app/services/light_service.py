"""
ESP32 Light Controller Service
Manages connection to ESP32 via HTTP API and broadcasts state changes via WebSocket.
"""
import asyncio
import logging
import aiohttp
from typing import Dict, List, Optional, Set
from urllib.parse import quote
from fastapi import WebSocket

from app.config import settings
from app.models.light import LightState

logger = logging.getLogger(__name__)


class LightControllerService:
    """Manages ESP32 HTTP connection, light states, and WebSocket broadcasts."""

    def __init__(self):
        self.lights: Dict[int, LightState] = {}
        self.connected: bool = False
        self._session: Optional[aiohttp.ClientSession] = None
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

    async def connect(self) -> bool:
        """Initialize HTTP session and check ESP32 connectivity."""
        try:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            )
            
            # Test connection by fetching the ESP32 page
            async with self._session.get(f"http://{settings.ESP32_HOST}/") as resp:
                if resp.status == 200:
                    self.connected = True
                    logger.info(f"Connected to ESP32 at {settings.ESP32_HOST}")
                else:
                    self.connected = False
                    logger.warning(f"ESP32 returned status {resp.status}")
            
            # Broadcast connection status
            await self._broadcast_state()
            return True

        except Exception as e:
            logger.warning(f"Could not connect to ESP32: {e}")
            logger.info("Running in simulation mode - states tracked locally")
            self.connected = False
            return False

    async def _send_light_command(self, light_name: str, on: bool, brightness: Optional[int] = None) -> bool:
        """Send HTTP command to ESP32."""
        if not self._session:
            return False
            
        try:
            encoded_name = quote(light_name)
            
            if on:
                url = f"http://{settings.ESP32_HOST}/light/{encoded_name}/turn_on"
                if brightness is not None:
                    # Convert 0-100% to 0-255
                    esp_brightness = int(brightness * 255 / 100)
                    url += f"?brightness={esp_brightness}"
            else:
                url = f"http://{settings.ESP32_HOST}/light/{encoded_name}/turn_off"
            
            async with self._session.post(url) as resp:
                if resp.status == 200:
                    logger.info(f"[ESP32] {light_name}: {'ON' if on else 'OFF'}" + 
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

        # Broadcast state change
        await self._broadcast_state()
        
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
            "message": "Connected to ESP32" if self.connected else "Running in simulation mode"
        }

    async def disconnect(self):
        """Close HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None
            self.connected = False
            logger.info("Disconnected from ESP32")

    # ─── WebSocket Management ───────────────────────────────────────

    async def register_websocket(self, websocket: WebSocket):
        """Register a new WebSocket client."""
        async with self._broadcast_lock:
            self._websocket_clients.add(websocket)
            logger.info(f"WebSocket client connected. Total: {len(self._websocket_clients)}")
        
        # Send initial state
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
                except Exception:
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
                except Exception:
                    dead_clients.add(client)

            self._websocket_clients -= dead_clients


# Singleton instance
light_service = LightControllerService()

"""Stream router: RTSP pipeline status/control + HLS reverse proxy."""
import logging

import aiohttp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.services.stream_service import stream_service

logger = logging.getLogger(__name__)

router = APIRouter()

_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60, connect=5)
        )
    return _session


async def close_session():
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None


@router.get("/status")
async def status():
    return await stream_service.status()


@router.post("/start")
async def start():
    return await stream_service.start()


@router.post("/stop")
async def stop():
    return stream_service.stop()


@router.get("/hls/{path:path}")
async def hls_proxy(path: str, request: Request):
    query = request.url.query
    url = f"http://{settings.MEDIAMTX_HOST}:{settings.MEDIAMTX_HLS_PORT}/{path}"
    if query:
        url += f"?{query}"
    session = _get_session()

    try:
        upstream = await session.get(url)
    except aiohttp.ClientError:
        raise HTTPException(status_code=503, detail="Stream server unavailable")

    if upstream.status != 200:
        await upstream.release()
        raise HTTPException(status_code=upstream.status, detail="Stream path not available")

    headers = {
        "Content-Type": upstream.headers.get("Content-Type", "application/octet-stream"),
        "Cache-Control": upstream.headers.get("Cache-Control", "no-cache"),
    }

    async def body():
        try:
            async for chunk in upstream.content.iter_chunked(65536):
                yield chunk
        finally:
            upstream.release()

    return StreamingResponse(body(), status_code=200, headers=headers)

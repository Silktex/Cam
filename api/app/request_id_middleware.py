"""
Request ID middleware for correlation tracking
"""
import uuid
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Pure-ASGI middleware that binds request_id, method, and route to contextvars.
    Every log line within the request will include these fields.
    """
    
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        
        bind_contextvars(
            request_id=request_id,
            method=request.method,
            route=str(request.url.path)
        )
        
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            clear_contextvars()

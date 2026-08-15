"""Tests for structured logging core."""
import asyncio
import json
import logging

import httpx
import pytest
import structlog
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.logging_setup import setup_logging
from app.request_id_middleware import RequestIdMiddleware


class MemoryHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


@pytest.fixture(scope="module")
def log_app():
    setup_logging(level=logging.INFO)

    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    log = structlog.get_logger(__name__)

    @app.get("/ping")
    async def ping():
        log.info("ping handled")
        return {"status": "ok"}

    return app


def test_concurrent_requests_get_distinct_request_ids(log_app):
    async def make_requests():
        transport = httpx.ASGITransport(app=log_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r1, r2 = await asyncio.gather(
                client.get("/ping"),
                client.get("/ping"),
            )
            return r1.headers["x-request-id"], r2.headers["x-request-id"]

    id1, id2 = asyncio.run(make_requests())
    assert id1 != id2
    assert len(id1) == 32


def test_request_id_visible_in_log_output(log_app):
    mem = MemoryHandler()
    mem.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
            ],
        )
    )
    root = logging.getLogger()
    root.addHandler(mem)
    try:
        client = TestClient(log_app)
        response = client.get("/ping")
        request_id = response.headers["x-request-id"]

        found = False
        for line in mem.records:
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if record.get("request_id") == request_id:
                found = True
                break

        assert found, f"request_id {request_id} not found in log output"
    finally:
        root.removeHandler(mem)


def test_unicode_multiline_exception_still_valid_json():
    """A unicode/multiline exception must still produce one valid JSON line."""
    setup_logging(level=logging.INFO)
    mem = MemoryHandler()
    mem.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
            ],
        )
    )
    root = logging.getLogger()
    root.addHandler(mem)
    try:
        svc = logging.getLogger("test.unicode")
        try:
            raise ValueError('unicode \u2713 with \n newline and "quotes" and \u4e2d\u6587')
        except ValueError:
            svc.exception("multiline exception context")

        assert len(mem.records) == 1
        # must parse as single-line JSON
        record = json.loads(mem.records[0])
        assert "exception" in record
        assert "\u2713" in record["exception"]
        assert "\u4e2d\u6587" in record["exception"]
    finally:
        root.removeHandler(mem)

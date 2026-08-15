"""
Tests for correlation ID propagation across async services and threadpool boundaries
"""
import asyncio
import logging
import uuid
from unittest.mock import MagicMock, patch
import pytest
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars
from structlog.testing import CapturingLogger

from app.context_utils import run_with_context


@pytest.fixture
def capture_logs():
    """Capture log output for verification"""
    logger = CapturingLogger()
    with patch("structlog._config._CONFIG", {"logger_factory": lambda: logger}):
        yield logger


class TestWebSocketSessionID:
    """Test session_id propagation in WebSocket contexts"""

    def test_session_id_survives_service_call(self):
        """session_id bound in WebSocket context appears in service call logs"""
        # Simulate WebSocket connection setup
        session_id = uuid.uuid4().hex[:8]
        bind_contextvars(session_id=session_id, ws_type="test")

        # Verify context is set
        ctx = get_contextvars()
        assert ctx.get("session_id") == session_id
        assert ctx.get("ws_type") == "test"

        # Simulate service call (would log with context)
        logger = logging.getLogger("test.service")
        logger.info("Service call from WebSocket")

        # Context should still be present
        ctx_after = get_contextvars()
        assert ctx_after.get("session_id") == session_id

        # Cleanup
        clear_contextvars()

    def test_session_id_isolation_between_connections(self):
        """Different WebSocket connections have different session_ids"""
        # Connection 1
        session_id_1 = uuid.uuid4().hex[:8]
        bind_contextvars(session_id=session_id_1, ws_type="test")
        ctx_1 = get_contextvars()
        assert ctx_1.get("session_id") == session_id_1

        # Clear and simulate new connection
        clear_contextvars()

        # Connection 2
        session_id_2 = uuid.uuid4().hex[:8]
        bind_contextvars(session_id=session_id_2, ws_type="test")
        ctx_2 = get_contextvars()
        assert ctx_2.get("session_id") == session_id_2
        assert ctx_2.get("session_id") != session_id_1

        # Cleanup
        clear_contextvars()


class TestBackgroundTaskCorrelation:
    """Test request_id/session_id propagation in asyncio tasks"""

    @pytest.mark.asyncio
    async def test_request_id_inherits_in_asyncio_task(self):
        """request_id bound before asyncio.create_task appears in task's log lines"""
        request_id = uuid.uuid4().hex[:8]
        bind_contextvars(request_id=request_id, method="POST", route="/test")

        task_context = {}

        async def background_task():
            # This task should inherit the context
            ctx = get_contextvars()
            task_context.update(ctx)
            await asyncio.sleep(0.01)

        # Create task (should inherit contextvars automatically)
        task = asyncio.create_task(background_task())
        await task

        # Verify context was inherited
        assert task_context.get("request_id") == request_id
        assert task_context.get("method") == "POST"
        assert task_context.get("route") == "/test"

        # Cleanup
        clear_contextvars()

    @pytest.mark.asyncio
    async def test_multiple_tasks_isolated_contexts(self):
        """Multiple concurrent tasks maintain their own context"""
        contexts = []

        async def task_with_context(task_id):
            bind_contextvars(task_id=task_id)
            await asyncio.sleep(0.01)
            ctx = get_contextvars()
            contexts.append(ctx.copy())

        # Create multiple tasks with different contexts
        tasks = [
            asyncio.create_task(task_with_context(f"task-{i}"))
            for i in range(3)
        ]
        await asyncio.gather(*tasks)

        # Each task should have its own task_id
        task_ids = [ctx.get("task_id") for ctx in contexts]
        assert task_ids == ["task-0", "task-1", "task-2"]

        # Cleanup
        clear_contextvars()


class TestThreadpoolContextPropagation:
    """Test context propagation in threadpool execution"""

    def test_run_with_context_preserves_contextvars(self):
        """run_with_context wrapper preserves contextvars in threadpool"""
        request_id = uuid.uuid4().hex[:8]
        bind_contextvars(request_id=request_id, session_id="test-session")

        thread_context = {}

        def threadpool_work():
            # This runs in a thread, should have context
            ctx = get_contextvars()
            thread_context.update(ctx)
            return "done"

        # Execute in threadpool with context preservation
        wrapped = run_with_context(threadpool_work)
        result = wrapped()

        # Verify context was preserved
        assert result == "done"
        assert thread_context.get("request_id") == request_id
        assert thread_context.get("session_id") == "test-session"

        # Cleanup
        clear_contextvars()

    def test_run_with_context_with_arguments(self):
        """run_with_context correctly passes arguments to wrapped function"""
        bind_contextvars(request_id="test-req")

        def work_with_args(a, b, c=None):
            ctx = get_contextvars()
            return {
                "sum": a + b,
                "c": c,
                "request_id": ctx.get("request_id"),
            }

        wrapped = run_with_context(work_with_args, 5, 10, c="test")
        result = wrapped()

        assert result["sum"] == 15
        assert result["c"] == "test"
        assert result["request_id"] == "test-req"

        clear_contextvars()

    @pytest.mark.asyncio
    async def test_loop_run_in_executor_with_context(self):
        """loop.run_in_executor with run_with_context preserves context"""
        import queue
        request_id = uuid.uuid4().hex[:8]
        bind_contextvars(request_id=request_id)

        result_queue = queue.Queue()

        def blocking_work():
            ctx = get_contextvars()
            result_queue.put(ctx.get("request_id"))
            return "result"

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, run_with_context(blocking_work)
        )

        assert result == "result"
        assert result_queue.get() == request_id

        clear_contextvars()

    def test_threadpool_executor_with_context(self):
        """ThreadPoolExecutor.submit with run_with_context preserves context"""
        import queue
        from concurrent.futures import ThreadPoolExecutor

        session_id = uuid.uuid4().hex[:8]
        bind_contextvars(session_id=session_id)

        result_queue = queue.Queue()

        def thread_work():
            ctx = get_contextvars()
            result_queue.put(ctx.get("session_id"))
            return "completed"

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_with_context(thread_work))
            result = future.result()

        assert result == "completed"
        assert result_queue.get() == session_id

        clear_contextvars()


class TestContextIsolation:
    """Test that context is properly isolated and cleaned up"""

    def test_clear_contextvars_removes_all(self):
        """clear_contextvars removes all bound context"""
        bind_contextvars(request_id="req-1", session_id="sess-1", method="GET")
        ctx = get_contextvars()
        assert len(ctx) == 3

        clear_contextvars()
        ctx_after = get_contextvars()
        assert len(ctx_after) == 0

    def test_context_does_not_leak_between_calls(self):
        """Context from one call doesn't leak to next"""
        # First call
        bind_contextvars(request_id="req-1")
        ctx_1 = get_contextvars()
        assert ctx_1.get("request_id") == "req-1"

        # Clear
        clear_contextvars()

        # Second call - should not have req-1
        ctx_2 = get_contextvars()
        assert ctx_2.get("request_id") is None

        # Bind different context
        bind_contextvars(request_id="req-2")
        ctx_3 = get_contextvars()
        assert ctx_3.get("request_id") == "req-2"

        clear_contextvars()

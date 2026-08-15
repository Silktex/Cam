"""Context propagation utilities for threadpool execution."""
from __future__ import annotations

import contextvars
from functools import partial
from typing import Any, Callable


def run_with_context(func: Callable, *args, **kwargs) -> Callable:
    """Wrap a function so it preserves contextvars when run in a threadpool.

    asyncio.create_task() inherits contextvars automatically, but
    loop.run_in_executor() and ThreadPoolExecutor.submit() do NOT. This wrapper
    captures the current context now and runs the callable within it.

    Usage:
        ctx_func = run_with_context(blocking_func, arg1, arg2)
        await loop.run_in_executor(None, ctx_func)
        executor.submit(ctx_func)
    """
    ctx = contextvars.copy_context()

    def wrapper() -> Any:
        return ctx.run(partial(func, *args, **kwargs))

    return wrapper

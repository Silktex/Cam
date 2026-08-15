"""
Context propagation utilities for threadpool execution
"""
import contextvars
from functools import partial
from typing import Any, Callable


def run_with_context(func: Callable, *args, **kwargs) -> Callable:
    """
    Wrap a function to preserve contextvars when executed in a threadpool.
    
    asyncio.create_task() inherits contextvars automatically,
    but loop.run_in_executor() and ThreadPoolExecutor.submit() do NOT.
    This wrapper captures the current context immediately and returns
    a callable that runs the function within that context.
    
    Usage:
        ctx_func = run_with_context(blocking_func, arg1, arg2)
        loop.run_in_executor(None, ctx_func)
        executor.submit(ctx_func)
    """
    ctx = contextvars.copy_context()
    def wrapper() -> Any:
        return ctx.run(partial(func, *args, **kwargs))
    return wrapper

"""Bound response waits without joining an in-flight SDK worker at every deadline."""

from __future__ import annotations

import asyncio
import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

from service.config import get_settings

_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_executor: ThreadPoolExecutor | None = None
_work: set = set()
_work_lock = threading.Lock()
_deadline = contextvars.ContextVar("agent_execution_deadline", default=None)


@contextmanager
def execution_budget(seconds: float):
    """Carry a deadline into SDK worker contexts, including fallback synthesis."""
    cancelled = threading.Event()
    token = _deadline.set((time.monotonic() + max(0, seconds), cancelled))
    try:
        yield
    finally:
        cancelled.set()
        _deadline.reset(token)


def check_budget() -> None:
    """Stop another model call after an earlier call consumed the turn's budget."""
    deadline = _deadline.get()
    if deadline is not None and (
        time.monotonic() >= deadline[0] or deadline[1].is_set()
    ):
        raise TimeoutError("Agent model-and-tool deadline expired")


class _TrackedExecutor(ThreadPoolExecutor):
    def submit(self, fn, /, *args, **kwargs):
        future = super().submit(fn, *args, **kwargs)
        with _work_lock:
            _work.add(future)

        def completed(done):
            with _work_lock:
                _work.discard(done)

        future.add_done_callback(completed)
        return future


def _runtime() -> tuple[asyncio.AbstractEventLoop, ThreadPoolExecutor]:
    global _loop, _executor
    with _lock:
        if _loop is None:
            _executor = _TrackedExecutor(
                max_workers=get_settings().max_concurrent_model_runs,
                thread_name_prefix="mosaic-agent-sdk",
            )
            _loop = asyncio.new_event_loop()
            _loop.set_default_executor(_executor)
            threading.Thread(
                target=_loop.run_forever, name="mosaic-agent-loop", daemon=True
            ).start()
        return _loop, _executor


def outstanding_work() -> int:
    """Count SDK workers still queued/running, including work outliving its caller."""
    with _work_lock:
        return len(_work)


def run_async(coroutine, *, timeout: float) -> Any:
    """Preserve request context on a process-owned loop and bound only the caller's wait."""
    if timeout <= 0:
        coroutine.close()
        raise TimeoutError("Agent model-and-tool deadline expired")
    loop, _ = _runtime()
    with execution_budget(timeout):
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise


async def offload(function, *args):
    """Share a bounded worker pool; cancelling the await never expands its capacity."""
    _, executor = _runtime()
    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(
        executor, context.run, function, *args
    )

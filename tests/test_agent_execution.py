"""Real worker waits must not turn a response deadline into an SDK timeout."""

import asyncio
import contextvars
import threading
import time

import pytest

from service.agent_execution import execution_budget, offload, run_async
from service.bedrock import converse


def test_offload_carries_the_request_context():
    current = contextvars.ContextVar("test_request", default="absent")
    token = current.set("this request")
    try:
        assert run_async(offload(current.get), timeout=1) == "this request"
    finally:
        current.reset(token)


@pytest.mark.parametrize("mode", ["expired", "cancelled"])
def test_finished_worker_cannot_start_another_model_call(mode):
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()

    class Client:
        def converse(self, **_):
            pytest.fail("a cancelled worker started another model call")

    def work():
        entered.set()
        assert release.wait(2)
        try:
            converse(Client())
        except TimeoutError:
            stopped.set()

    async def run():
        with execution_budget(0.02 if mode == "expired" else 5):
            task = asyncio.create_task(offload(work))
            while not entered.is_set():
                await asyncio.sleep(0.001)
            if mode == "expired":
                await asyncio.sleep(0.03)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        release.set()

    asyncio.run(run())
    assert stopped.wait(1)


def test_no_remaining_budget_does_not_start_the_coroutine():
    async def forbidden():
        pytest.fail("work began with no remaining budget")

    with pytest.raises(TimeoutError):
        run_async(forbidden(), timeout=0)


def test_caller_does_not_join_a_running_worker():
    release = threading.Event()
    entered = threading.Event()

    def work():
        entered.set()
        release.wait(2)

    started = time.perf_counter()
    try:
        with pytest.raises(TimeoutError):
            run_async(offload(work), timeout=0.05)
        assert entered.is_set()
        assert time.perf_counter() - started < 0.3
    finally:
        release.set()

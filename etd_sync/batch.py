"""Bounded queries with globally paced starts and serialized result handling."""
import asyncio
import math
import time


async def query_batch(entries, fetch, on_start, on_result, *, concurrency=2, interval=1):
    """entries are (row index, order number); callbacks run on the event-loop thread.

    Each worker has one browser context. Result handling is serialized, while
    other workers may continue querying. Starts are spaced globally, not per worker.
    """
    if not 1 <= concurrency <= 3 or not math.isfinite(interval) or interval < 0:
        raise ValueError('并发数须为 1–3，查询间隔须为非负有限数')
    queue = asyncio.Queue()
    for entry in entries:
        queue.put_nowait(entry)
    pace_lock, result_lock = asyncio.Lock(), asyncio.Lock()
    next_start = 0.0

    async def worker(lane):
        nonlocal next_start
        while not queue.empty():
            try:
                index, number = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            async with pace_lock:
                # Windows event-loop timers may wake early; recheck the deadline.
                while (remaining := next_start - time.perf_counter()) > 0:
                    await asyncio.sleep(remaining)
                on_start(index)
                next_start = time.perf_counter() + interval
            started = time.perf_counter()
            try:
                result, error = await fetch(number, lane), None
            except Exception as exc:
                result, error = None, exc
            duration = time.perf_counter() - started
            async with result_lock:
                await on_result(index, result, error, duration)

    workers = [asyncio.create_task(worker(lane)) for lane in range(min(concurrency, len(entries)))]
    try:
        await asyncio.gather(*workers)
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

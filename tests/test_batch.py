import asyncio
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from etd_sync.batch import query_batch
from etd_sync.evergreen import EvergreenClient


class BatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_pacing_rechecks_early_timer_wakeup(self):
        original_sleep = asyncio.sleep
        woke_early = False
        starts = []
        async def sleep(delay):
            nonlocal woke_early
            if delay > 0 and not woke_early:
                woke_early = True
                return
            await original_sleep(delay)
        async def fetch(number, lane):
            return number
        async def result(*args):
            pass
        with patch('etd_sync.batch.asyncio.sleep', side_effect=sleep):
            await asyncio.wait_for(query_batch([(0, 'A'), (1, 'B')], fetch,
                lambda i: starts.append(time.perf_counter()), result,
                concurrency=2, interval=.02), timeout=1)
        self.assertTrue(woke_early)
        self.assertGreaterEqual(starts[1] - starts[0], .019)

    async def test_bounded_out_of_order_queries_and_serial_writes(self):
        active = peak = writing = write_peak = 0
        seen, completed, starts = {}, [], []
        async def fetch(number, lane):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(.08 if number == 'SLOW' else .01)
                if number == 'FAIL':
                    raise ValueError('test failure')
                return number + '-ETD'
            finally:
                active -= 1
        async def result(index, value, error, seconds):
            nonlocal writing, write_peak
            writing += 1
            write_peak = max(write_peak, writing)
            await asyncio.sleep(.01)
            seen[index] = error if error else value
            completed.append(index)
            self.assertGreater(seconds, 0)
            writing -= 1
        entries = list(enumerate(['SLOW', 'FAST', 'FAIL', 'LAST']))
        await query_batch(entries, fetch, lambda i: starts.append(time.perf_counter()),
                          result, concurrency=2, interval=.015)
        self.assertEqual(peak, 2)
        self.assertEqual(write_peak, 1)
        self.assertEqual(seen[0], 'SLOW-ETD')
        self.assertEqual(seen[1], 'FAST-ETD')
        self.assertIsInstance(seen[2], ValueError)
        self.assertEqual(seen[3], 'LAST-ETD')
        self.assertEqual(completed[0], 1)
        self.assertTrue(all(b-a >= .012 for a,b in zip(starts,starts[1:])))

    async def test_serial_mode_and_invalid_settings(self):
        completed = []
        async def fetch(number, lane):
            return number
        async def result(index, value, error, seconds):
            completed.append(index)
        await query_batch([(i,str(i)) for i in range(3)], fetch, lambda i: None, result,
                          concurrency=1, interval=0)
        self.assertEqual(completed, [0,1,2])
        for concurrency, interval in ((0,0),(4,0),(2,-1),(2,float('nan'))):
            with self.assertRaises(ValueError):
                await query_batch([],fetch,lambda i: None,result,concurrency=concurrency,interval=interval)

    async def test_session_launches_once_and_isolates_lanes(self):
        pages = []
        contexts = []
        for lane in range(2):
            locator = Mock()
            locator.wait_for = AsyncMock()
            locator.click = AsyncMock()
            locator.check = AsyncMock()
            locator.fill = AsyncMock()
            locator.is_visible = AsyncMock(return_value=False)
            locator.first = locator
            locator.locator.return_value = locator
            page = Mock()
            page.goto = AsyncMock()
            page.route = AsyncMock()
            page.content = AsyncMock(return_value=f'lane-{lane}')
            page.locator.return_value = locator
            page.get_by_text.return_value = locator
            context = Mock(new_page=AsyncMock(return_value=page))
            pages.append(page)
            contexts.append(context)
        browser = Mock(new_context=AsyncMock(side_effect=contexts), close=AsyncMock())
        playwright = Mock(chromium=Mock(launch=AsyncMock(return_value=browser)), stop=AsyncMock())
        factory = Mock(start=AsyncMock(return_value=playwright))
        with patch('playwright.async_api.async_playwright', return_value=factory), \
             patch('etd_sync.evergreen.extract_etd', side_effect=lambda html: html):
            async with EvergreenClient().session(2) as session:
                results = await asyncio.gather(session.fetch('A',0), session.fetch('B',1))
                self.assertEqual(results, ['lane-0','lane-1'])
                self.assertEqual(await session.fetch('C',0), 'lane-0')
        playwright.chromium.launch.assert_awaited_once()
        self.assertEqual(browser.new_context.await_count,2)
        self.assertEqual(pages[0].goto.await_count,2)
        self.assertEqual(pages[1].goto.await_count,1)
        browser.close.assert_awaited_once()
        playwright.stop.assert_awaited_once()

    async def test_failed_launch_stops_driver(self):
        playwright = Mock(chromium=Mock(launch=AsyncMock(side_effect=RuntimeError('launch failed'))),
                          stop=AsyncMock())
        with patch('playwright.async_api.async_playwright',return_value=Mock(start=AsyncMock(return_value=playwright))):
            with self.assertRaises(RuntimeError):
                async with EvergreenClient().session(2):
                    self.fail('not reached')
        playwright.stop.assert_awaited_once()

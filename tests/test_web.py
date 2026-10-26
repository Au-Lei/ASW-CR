import re
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from etd_sync.web import Console, create_app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {'WPS_SHEET_NAME': '工作表1', 'DATE_YEAR': '2026',
                       'QUERY_INTERVAL_SECONDS': '0', 'WPS_API_TOKEN': 'secret-token',
                       'WPS_WEBHOOK_URL': 'https://example.invalid/secret'}
        self.orders = [dict(order_no='CHANGED', original_etd='2026-10-21', latest_etd='2026-10-25'),
                       dict(order_no='SAME', original_etd='2026-10-21', latest_etd=None),
                       dict(order_no='FAIL', original_etd='2026-10-21', latest_etd='2026-10-25')]
        self.wps = Mock()
        self.wps.read.side_effect = lambda: [dict(o) for o in self.orders]
        def fetch(number):
            if number == 'FAIL':
                raise ValueError('查询失败 secret-token https://example.invalid/secret')
            return {'etd': date(2026, 10, 26) if number == 'CHANGED' else date(2026, 10, 21), 'pol': 'QINGDAO'}
        self.service = Console(Path(self.tmp.name) / 'test.sqlite3', self.config,
                               wps_factory=lambda: self.wps, fetch_factory=lambda: fetch)
        self.app = create_app(self.config, console=self.service)
        self.client = self.app.test_client()
        self.token = re.search(r'name="csrf-token" content="([^"]+)"',
                               self.client.get('/').text).group(1)

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, mode='sync'):
        return self.client.post('/api/jobs', json={'mode': mode}, headers={'X-CSRF-Token': self.token})

    def wait(self):
        for _ in range(150):
            snapshot = self.service.snapshot()
            if snapshot['jobs'] and snapshot['jobs'][0]['status'] != 'running':
                return snapshot
            time.sleep(.02)
        self.fail('worker did not complete')

    def test_sync_statistics_history_and_preserve_failure(self):
        self.assertEqual(self.submit().status_code, 202)
        snapshot = self.wait()
        job = snapshot['jobs'][0]
        self.assertEqual(job['status'], 'partial')
        self.assertEqual([i['status'] for i in job['items']], ['updated', 'unchanged', 'failed'])
        self.assertEqual(job['items'][0]['before_etd'], '2026-10-25')
        self.assertEqual(job['items'][0]['queried_etd'], '2026-10-26')
        self.assertEqual(snapshot['orders'][0]['latest_etd'], '2026-10-26')
        self.assertEqual(snapshot['orders'][2]['latest_etd'], '2026-10-25')
        self.assertIsNone(snapshot['orders'][2]['last_checked'])
        self.wps.update.assert_called_once()
        response = self.client.get('/api/state')
        self.assertNotIn('secret-token', response.text)
        self.assertNotIn('example.invalid', response.text)
        self.assertEqual(Console(self.service.path, self.config).snapshot()['jobs'][0]['id'], job['id'])

    def test_security_and_read_only(self):
        self.assertEqual(self.client.post('/api/jobs', json={'mode': 'sync'}).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'Host': 'attacker.example'}).status_code, 400)
        self.assertEqual(self.submit('read').status_code, 202)
        self.assertEqual(self.wait()['jobs'][0]['total'], 3)
        self.wps.update.assert_not_called()

    def test_duplicate_click_and_interrupted_recovery(self):
        event = threading.Event()
        self.wps.read.side_effect = lambda: (event.wait(2) or self.orders)
        try:
            self.assertEqual(self.submit('read').status_code, 202)
            self.assertEqual(self.submit('sync').status_code, 409)
        finally:
            event.set()
            self.wait()
        job = self.service.snapshot()['jobs'][0]
        job['status'] = 'running'
        self.service.save_job(job)
        recovered = Console(self.service.path, self.config).snapshot()['jobs'][0]
        self.assertEqual(recovered['status'], 'interrupted')

    def test_write_error_is_failure_not_success(self):
        self.wps.update.side_effect = RuntimeError('写入未确认')
        self.submit()
        snapshot = self.wait()
        self.assertEqual(snapshot['jobs'][0]['items'][0]['status'], 'failed')
        self.assertEqual(snapshot['orders'][0]['latest_etd'], '2026-10-25')
        self.assertIsNotNone(snapshot['orders'][0]['last_checked'])
        item = snapshot['jobs'][0]['items'][0]
        self.assertEqual(item['failure_stage'], 'write')
        self.assertIn('待确认', item['message'])
        self.assertIsNotNone(item['processed_at'])

    def test_external_edit_resets_current_overview(self):
        self.submit()
        self.wait()
        self.orders[0]['original_etd'] = '2026-10-20'
        self.submit('read')
        snapshot = self.wait()
        self.assertEqual(snapshot['orders'][0]['status'], 'unqueried')
        self.assertIn('已变化', snapshot['orders'][0]['message'])

    def test_failure_records_current_attempt_not_old_success(self):
        self.service.save_orders([{**order, 'last_checked': '2020-01-01T00:00:00+08:00'}
                                  for order in self.orders])
        self.submit()
        item = self.wait()['jobs'][0]['items'][2]
        self.assertEqual(item['last_checked'], '2020-01-01T00:00:00+08:00')
        self.assertNotEqual(item['processed_at'], item['last_checked'])

    def test_concurrent_results_write_correct_rows_one_at_a_time(self):
        self.orders = [dict(order_no=str(i), original_etd='2026-10-01',latest_etd=None)
                       for i in range(6)]
        active = peak = 0
        written = {}
        def fetch(number):
            time.sleep(.06 if int(number)%2==0 else .005)
            return {'etd':date(2026,10,10+int(number))}
        def update(order, latest):
            nonlocal active, peak
            active += 1
            peak = max(peak,active)
            time.sleep(.01)
            written[order['order_no']] = latest.isoformat()
            active -= 1
        self.service.fetch_factory = lambda:fetch
        self.wps.update.side_effect = update
        self.submit()
        snapshot = self.wait()
        self.assertEqual(snapshot['jobs'][0]['status'],'completed')
        self.assertEqual(snapshot['jobs'][0]['processed'],6)
        self.assertEqual(peak,1)
        self.assertEqual(written,{str(i):f'2026-10-{10+i}' for i in range(6)})
        for order in snapshot['orders']:
            self.assertEqual(order['latest_etd'],written[order['order_no']])
        self.assertGreater(snapshot['jobs'][0]['duration_seconds'],0)

    def test_invalid_rows_do_not_start_browser(self):
        self.orders = [dict(order_no='DUP',original_etd='2026-10-01',latest_etd=None)]*2
        self.service.fetch_factory=Mock(side_effect=AssertionError('must not start'))
        self.submit()
        snapshot=self.wait()
        self.service.fetch_factory.assert_not_called()
        self.assertEqual(snapshot['jobs'][0]['processed'],2)
        self.assertTrue(all(i['status']=='failed' for i in snapshot['jobs'][0]['items']))


if __name__ == '__main__':
    unittest.main()

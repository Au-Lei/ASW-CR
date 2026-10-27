import re
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_javascript_mime_ignores_windows_file_associations(self):
        with patch('mimetypes.guess_type', return_value=('text/plain', None)):
            for filename in ('console.js', 'console-model.mjs'):
                response = self.client.get('/static/' + filename)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'text/javascript')
                response.close()

    def submit(self, mode='sync'):
        return self.client.post('/api/jobs', json={'mode': mode}, headers={'X-CSRF-Token': self.token})

    def submit_selected(self, numbers):
        return self.client.post('/api/jobs', json={'mode': 'sync', 'order_nos': numbers},
                                headers={'X-CSRF-Token': self.token})

    def test_selected_sync_preserves_unselected_rows_and_result_identity(self):
        self.service.save_orders([{**o, 'status': 'unchanged', 'last_checked': '2026-10-20T12:00:00+08:00',
            'queried_etd': '2026-10-21', 'before_etd': None} for o in self.orders])
        def fetch(number):
            time.sleep(.04 if number == 'CHANGED' else .001)
            return {'etd': date(2026, 10, 26 if number == 'CHANGED' else 27)}
        fetch_mock = Mock(side_effect=fetch)
        self.service.fetch_factory = lambda: fetch_mock
        self.assertEqual(self.submit_selected(['FAIL', ' CHANGED ', 'CHANGED']).status_code, 202)
        snapshot = self.wait()
        job = snapshot['jobs'][0]
        self.assertEqual((job['scope'], job['total'], job['processed']), ('selected', 2, 2))
        self.assertEqual([i['order_no'] for i in job['items']], ['CHANGED', 'FAIL'])
        self.assertEqual({c.args[0] for c in fetch_mock.call_args_list}, {'CHANGED', 'FAIL'})
        self.assertEqual({c.args[0]['order_no']: c.args[1].isoformat() for c in self.wps.update.call_args_list},
                         {'CHANGED': '2026-10-26', 'FAIL': '2026-10-27'})
        self.assertEqual(len(snapshot['orders']), 3)
        other = snapshot['orders'][1]
        self.assertEqual(other['order_no'], 'SAME')
        self.assertEqual(other['status'], 'unchanged')
        self.assertIsNone(other['latest_etd'])
        self.assertEqual(other['last_checked'], '2026-10-20T12:00:00+08:00')
        self.assertEqual(other['queried_etd'], '2026-10-21')

    def test_selected_sync_rejects_missing_and_duplicate_sheet_numbers(self):
        self.service.fetch_factory = Mock(side_effect=AssertionError('must not query'))
        self.assertEqual(self.submit_selected(['CHANGED', 'REMOVED']).status_code, 202)
        job = self.wait()['jobs'][0]
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['items'], [])
        self.assertIn('已不在 WPS', job['message'])
        self.orders.append(dict(self.orders[0]))
        self.submit_selected(['CHANGED'])
        job = self.wait()['jobs'][0]
        self.assertEqual(job['status'], 'partial')
        self.assertEqual(len(job['items']), 2)
        self.assertTrue(all('重复' in item['message'] for item in job['items']))
        self.service.fetch_factory.assert_not_called()
        self.wps.update.assert_not_called()

    def test_selected_sync_batch_failure_maps_to_actual_row(self):
        self.service.fetch_factory = Mock(side_effect=RuntimeError('浏览器启动失败'))
        self.submit_selected(['FAIL'])
        snapshot = self.wait()
        self.assertEqual(snapshot['jobs'][0]['status'], 'failed')
        self.assertEqual([o['status'] for o in snapshot['orders']], ['unqueried', 'unqueried', 'failed'])
        self.assertEqual(snapshot['jobs'][0]['processed'], 1)
        self.wps.update.assert_not_called()

    def test_invalid_selection_never_starts_a_job(self):
        for numbers in (None, [], '', 'CHANGED', [1], [' '], ['X' * 201], ['X'] * 5001):
            with self.subTest(numbers=repr(numbers)[:40]):
                self.assertEqual(self.submit_selected(numbers).status_code, 400)
        response = self.client.post('/api/jobs', json={'mode': 'read', 'order_nos': ['CHANGED']},
                                    headers={'X-CSRF-Token': self.token})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.service.snapshot()['jobs'], [])
        self.wps.read.assert_not_called()

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

    def test_invalid_json_shapes_do_not_create_jobs(self):
        for payload in ([1], 'sync', 1, True, None, {}, {'mode': ['sync']}):
            with self.subTest(payload=payload):
                response = self.client.post('/api/jobs', json=payload,
                                            headers={'X-CSRF-Token': self.token})
                self.assertEqual(response.status_code, 400)
                self.assertIsNotNone(response.json.get('error'))
        self.assertEqual(self.service.snapshot()['jobs'], [])
        self.wps.read.assert_not_called()

    def test_non_ascii_csrf_is_rejected_without_server_error(self):
        response = self.client.post('/api/jobs', json={'mode': 'sync'},
                                    headers={'X-CSRF-Token': '过期令牌'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.service.snapshot()['jobs'], [])

    def test_worker_start_failure_is_recorded_and_allows_next_job(self):
        with patch('etd_sync.service.threading.Thread.start',
                   side_effect=RuntimeError('cannot start worker secret-token')):
            response = self.submit()
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('secret-token', response.text)
        job = self.service.snapshot()['jobs'][0]
        self.assertEqual(job['status'], 'failed')
        self.assertIsNotNone(job['finished_at'])
        self.assertNotIn('secret-token', job['message'])
        self.wps.read.assert_not_called()
        self.assertEqual(self.submit('read').status_code, 202)
        self.assertEqual(self.wait()['jobs'][0]['status'], 'completed')

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

    def test_history_only_records_successful_changes_after_valid_to(self):
        limits = {'LATE': '2026-10-25', 'EQUAL': '2026-10-26',
                  'BEFORE': '2026-10-27', 'EMPTY': None, 'INVALID': 'bad',
                  'SERIAL': 46320, 'LEGACY': '10.25', 'FAIL': '2026-10-25',
                  'UNCHANGED': '2026-10-01'}
        self.orders = [dict(order_no=number, original_etd='2026-10-01',
                            latest_etd='2026-10-26' if number == 'UNCHANGED' else None,
                            valid_to=limit) for number, limit in limits.items()]
        self.orders.append(dict(order_no='MISSING', original_etd='2026-10-01', latest_etd=None))
        def fetch(number):
            if number == 'FAIL':
                raise ValueError('查询失败')
            return {'etd': date(2026, 10, 26)}
        self.service.fetch_factory = lambda: fetch
        self.submit()
        snapshot = self.wait()
        self.assertEqual({i['order_no'] for i in snapshot['changes']}, {'LATE', 'SERIAL', 'LEGACY'})

        self.assertTrue(all(i['valid_to'] == '2026-10-25' for i in snapshot['changes']))
        self.assertEqual(snapshot['orders'][0]['valid_to'], '2026-10-25')
        # The history filter never suppresses otherwise valid ETD writes.
        self.assertEqual(self.wps.update.call_count, 8)
        self.assertNotIn('同步任务记录', self.client.get('/').text)

        # Read-only tasks cannot push older qualifying changes out of history.
        for index in range(31):
            self.service.save_job(dict(id=f'read-{index}', mode='read', status='completed',
                                       created_at=f'2099-01-01T00:00:{index:02}+08:00', items=[]))
        snapshot = Console(self.service.path, self.config).snapshot()
        self.assertEqual(len(snapshot['jobs']), 30)
        self.assertEqual({i['order_no'] for i in snapshot['changes']}, {'LATE', 'SERIAL', 'LEGACY'})

    def test_sync_writes_business_status_even_without_an_etd_change(self):
        self.orders = [dict(order_no=n, original_etd='2026-10-28', latest_etd=saved,
                            valid_to='2026-10-30', current_status=status)
                       for n, saved, status in [('ORIGINAL', None, None), ('SHIFT', None, None),
                       ('ROLL', None, None), ('DONE', '2026-10-26', '托班到下一批次'),
                       ('SAME', None, 'ETD未变更'), ('FAIL', None, 'ETD已变更')]]
        days = {'ORIGINAL': 28, 'SHIFT': 29, 'ROLL': 31, 'DONE': 26, 'SAME': 28}
        def fetch(number):
            if number == 'FAIL':
                raise ValueError('官网查询失败')
            return {'etd': date(2026, 10, days[number])}
        self.service.fetch_factory = lambda: fetch
        with patch('etd_sync.service.now', return_value='2026-10-27T12:00:00+08:00'):
            self.submit()
            snapshot = self.wait()
        statuses = {o['order_no']: o['current_status'] for o in snapshot['orders']}
        self.assertEqual(statuses, dict(ORIGINAL='ETD未变更', SHIFT='ETD已变更',
            ROLL='托班到下一批次', DONE='已完成', SAME='ETD未变更', FAIL='ETD已变更'))
        self.assertEqual(self.wps.update.call_count, 2)
        self.assertEqual(self.wps.update_status.call_count, 2)
        self.assertEqual({c.args[0]['order_no'] for c in self.wps.update_status.call_args_list}, {'ORIGINAL', 'DONE'})
        self.assertEqual({c.kwargs['current_status'] for c in self.wps.update.call_args_list}, {'ETD已变更', '托班到下一批次'})
        items = {i['order_no']: i for i in snapshot['jobs'][0]['items']}
        self.assertEqual(items['DONE']['status'], 'unchanged')
        self.assertIn('status_written_at', items['DONE'])
        self.assertEqual(items['FAIL']['status'], 'failed')

    def test_failed_business_status_write_preserves_old_status(self):
        self.orders = [dict(order_no='TEST', original_etd='2026-10-28', latest_etd=None,
                            valid_to='2026-10-30', current_status='ETD已变更')]
        self.service.fetch_factory = lambda: lambda n: {'etd': date(2026, 10, 28)}
        self.wps.update_status.side_effect = RuntimeError('状态写入超时')
        with patch('etd_sync.service.now', return_value='2026-10-27T12:00:00+08:00'):
            self.submit()
            snapshot = self.wait()
        self.assertEqual(snapshot['orders'][0]['current_status'], 'ETD已变更')
        self.assertEqual(snapshot['jobs'][0]['items'][0]['failure_stage'], 'write')
        self.assertIn('待确认', snapshot['jobs'][0]['items'][0]['message'])
        self.wps.update.assert_not_called()



if __name__ == '__main__':
    unittest.main()

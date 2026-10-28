"""Offline API/service/client contract checks; all writes use an isolated fake WPS."""
import copy
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from etd_sync.__main__ import run
from etd_sync.orders import reconcile_orders
from etd_sync.service import Console
from etd_sync.wps import WpsClient


class PortSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rows = [dict(order_no=n, original_etd='2026-10-28', latest_etd=None,
                         valid_to='2026-10-30', current_status='ETD未变更',
                         pol='SHANGHAI', pod=None, remark='人工备注') for n in ('ONE', 'TWO')]
        self.results = {n: dict(etd=date(2026, 10, 28), pol='QINGDAO', pod='HAMBURG',
                               pol_raw='QINGDAO (CN)', pod_raw='HAMBURG (DE)') for n in ('ONE', 'TWO')}
        self.calls = []
        self.wps = WpsClient('https://www.kdocs.cn/api/v3/ide/file/demo/script/demo/sync_task', 'test', '工作表1')
        self.wps.call = Mock(side_effect=self.bridge)
        self.fetch = Mock(side_effect=lambda n: self.results[n])
        self.service = Console(Path(self.tmp.name) / 'test.sqlite3', {'QUERY_INTERVAL_SECONDS': '0'},
                               wps_factory=lambda: self.wps, fetch_factory=lambda: self.fetch)

    def tearDown(self):
        self.tmp.cleanup()

    def bridge(self, action, **args):
        if action == 'read':
            return dict(ok=True, schema_version=2, orders=copy.deepcopy(self.rows))
        self.calls.append((action, copy.deepcopy(args)))
        row = next(r for r in self.rows if r['order_no'] == args['order_no'])
        expected = {'original_etd': 'expected_original', 'latest_etd': 'expected_latest',
                    'valid_to': 'expected_valid_to', 'current_status': 'expected_status',
                    'pol': 'expected_pol', 'pod': 'expected_pod'}
        for field, key in expected.items():
            if key in args and row.get(field) != args[key]:
                raise RuntimeError('查询期间该行已被修改')
        for key in ('latest_etd', 'current_status', 'pol', 'pod'):
            if key in args:
                row[key] = args[key]
        return dict(ok=True, schema_version=2, **copy.deepcopy(row))

    def sync(self, targets=None, mode='sync'):
        with patch('etd_sync.service.now', return_value='2026-10-27T12:00:00+08:00'):
            job_id = self.service.start(mode, targets)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                state = self.service.snapshot()
                job = next(j for j in state['jobs'] if j['id'] == job_id)
                if job['status'] != 'running':
                    return state, job
                time.sleep(.01)
        self.fail('offline sync did not finish')

    def test_all_single_and_selected_share_ports_only_flow(self):
        for targets in (None, ['ONE'], ['ONE', 'TWO']):
            with self.subTest(targets=targets):
                for row in self.rows:
                    row.update(pol='SHANGHAI', pod=None)
                self.calls.clear()
                self.fetch.reset_mock()
                state, job = self.sync(targets)
                wanted = set(targets or ['ONE', 'TWO'])
                self.assertEqual(job['status'], 'completed')
                self.assertEqual({c.args[0] for c in self.fetch.call_args_list}, wanted)
                self.assertEqual(len(self.calls), len(wanted))
                self.assertTrue(all(action == 'update_ports' for action, _ in self.calls))
                self.assertTrue(all(i['status'] == 'unchanged' for i in job['items']))
                self.assertTrue(all(i['ports_updated'] == ['pol', 'pod'] for i in job['items']))
                self.assertEqual(state['changes'], [])
                for row in state['orders']:
                    self.assertEqual(row['pol'], 'QINGDAO' if row['order_no'] in wanted else 'SHANGHAI')
                    self.assertIsNone(row['latest_etd'])
                    self.assertEqual(row['remark'], '人工备注')
                for _, payload in self.calls:
                    self.assertNotIn('latest_etd', payload)
                    self.assertNotIn('remark', payload)
                    self.assertEqual(payload['expected_pol'], 'SHANGHAI')
                    self.assertIsNone(payload['expected_pod'])

    def test_etd_and_ports_are_one_confirmed_write_with_history_snapshot(self):
        self.results['ONE']['etd'] = date(2026, 10, 31)
        state, job = self.sync(['ONE'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], 'update')
        item = job['items'][0]
        self.assertEqual((item['status'], item['current_status']), ('updated', '托班到下一批次'))
        self.assertEqual(state['orders'][0]['latest_etd'], '2026-10-31')
        self.assertEqual(state['changes'][0]['pod'], 'HAMBURG')
        self.assertEqual(state['changes'][0]['remark'], '人工备注')
        # A read refreshes live WPS values without rewriting the saved history.
        self.rows[0].update(pol='NINGBO', remark='后来改的备注')
        state, _ = self.sync(mode='read')
        self.assertEqual(state['orders'][0]['pol'], 'NINGBO')
        self.assertEqual(state['orders'][0]['remark'], '后来改的备注')
        self.assertEqual(state['changes'][0]['remark'], '人工备注')
        self.assertEqual(state['changes'][0]['pol'], 'QINGDAO')
        restored = Console(self.service.path, {}).snapshot()
        self.assertEqual(restored['changes'], state['changes'])

    def test_missing_port_preserves_old_value_and_surfaces_warning(self):
        self.rows[0]['pod'] = 'OLD PORT'
        self.results['ONE']['pod'] = None
        state, job = self.sync(['ONE'])
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(state['orders'][0]['pod'], 'OLD PORT')
        item = job['items'][0]
        self.assertEqual(item['ports_updated'], ['pol'])
        self.assertIn('目的港', item['warnings'][0])
        self.assertIn('保留表格原值', item['message'])
        self.assertNotIn('pod', self.calls[0][1])
        self.assertIsNone(item['queried_pod'])

    def test_repeat_sync_is_noop_and_status_still_updates(self):
        self.sync(['ONE'])
        self.calls.clear()
        self.sync(['ONE'])
        self.assertEqual(self.calls, [])
        self.rows[0]['current_status'] = 'ETD已变更'
        state, job = self.sync(['ONE'])
        self.assertEqual(self.calls[0][0], 'update_status')
        self.assertEqual(state['orders'][0]['current_status'], 'ETD未变更')
        self.assertEqual(job['items'][0]['ports_updated'], [])

    def test_port_only_after_valid_to_never_enters_etd_history(self):
        self.rows[0].update(valid_to='2026-10-26')
        state, job = self.sync(['ONE'])
        self.assertEqual(state['changes'], [])
        self.assertEqual(job['items'][0]['status'], 'unchanged')
        self.assertEqual(state['orders'][0]['current_status'], '托班到下一批次')
        self.assertEqual(self.calls[0][0], 'update_ports')

    def test_conflict_and_unconfirmed_write_never_promote_queried_values(self):
        original = self.bridge
        for failure in ('conflict', 'wrong_port', 'old_script', 'wrong_etd'):
            with self.subTest(failure=failure):
                self.rows[0].update(pol='SHANGHAI', pod=None, latest_etd=None, current_status='ETD未变更')
                self.results['ONE']['etd'] = date(2026, 10, 31)
                def broken(action, **args):
                    if action == 'read':
                        return original(action, **args)
                    if failure == 'conflict':
                        raise RuntimeError('查询期间该行已被修改')
                    result = original(action, **args)
                    if failure == 'wrong_port':
                        result['pod'] = 'OTHER'
                    elif failure == 'wrong_etd':
                        result['latest_etd'] = None
                    else:
                        result.pop('schema_version')
                    return result
                self.wps.call.side_effect = broken
                state, job = self.sync(['ONE'])
                item = job['items'][0]
                self.assertEqual((job['status'], item['status'], item['failure_stage']), ('partial', 'failed', 'write'))
                self.assertIn('待确认', item['message'])
                self.assertEqual(state['orders'][0]['pol'], 'SHANGHAI')
                self.assertIsNone(state['orders'][0]['latest_etd'])
                self.assertEqual(item['ports_updated'], [])
                self.assertEqual(state['changes'], [])
                self.assertEqual(item['queried_pod'], 'HAMBURG')

    def test_legacy_sheets_and_legacy_history_keep_working(self):
        for row in self.rows:
            del row['pol'], row['pod']
        self.results['ONE']['etd'] = date(2026, 10, 31)
        state, _ = self.sync(['ONE'])
        self.assertEqual(self.calls[0][0], 'update')
        self.assertNotIn('pol', self.calls[0][1])
        self.assertEqual(len(state['changes']), 1)
        self.sync(['ONE'])
        self.assertEqual(len(self.calls), 1)  # locally cached pol must not enable port writes

    def test_read_uses_wps_ports_and_remark_without_reset_for_note_only_edit(self):
        raw = copy.deepcopy(self.rows)
        old = [{**raw[0], 'status': 'updated', 'queried_etd': '2026-10-28', 'pol': 'OLD CACHE'}]
        result = reconcile_orders(raw, old)
        self.assertEqual(result[0]['pol'], 'SHANGHAI')
        self.assertEqual(result[0]['status'], 'unqueried')
        old = [{**raw[0], 'status': 'unchanged', 'queried_etd': '2026-10-28'}]
        raw[0]['remark'] = '新备注'
        result = reconcile_orders(raw, old)
        self.assertEqual(result[0]['remark'], '新备注')
        self.assertEqual(result[0]['status'], 'unchanged')

    def test_missing_both_ports_still_writes_valid_etd_and_keeps_ports(self):
        self.results['ONE'] = {'etd': date(2026, 10, 31), 'pol': None, 'pod': None}
        self.rows[0]['pod'] = 'KEEP'
        state, job = self.sync(['ONE'])
        self.assertEqual(job['etd_updated_count'], 1)
        self.assertEqual(job['ports_updated_count'], 0)
        self.assertEqual(job['warning_count'], 1)
        self.assertEqual(len(job['items'][0]['warnings']), 2)
        self.assertEqual(state['orders'][0]['pol'], 'SHANGHAI')
        self.assertEqual(state['orders'][0]['pod'], 'KEEP')
        self.assertEqual(state['orders'][0]['latest_etd'], '2026-10-31')
        self.assertNotIn('pol', self.calls[0][1])
        self.assertNotIn('pod', self.calls[0][1])

    def test_invalid_port_causes_no_write(self):
        self.results['ONE']['pod'] = '=FORMULA()'
        state, job = self.sync(['ONE'])
        self.assertEqual(job['items'][0]['failure_stage'], 'query')
        self.assertEqual(self.calls, [])
        self.assertEqual(state['orders'][0]['pol'], 'SHANGHAI')

    def test_old_history_without_port_fields_loads_unchanged(self):
        self.service.save_job(dict(id='legacy', mode='sync', status='completed',
            created_at='2026-10-20T00:00:00+08:00', items=[dict(order_no='OLD',
            original_etd='2026-10-19', latest_etd=None, queried_etd='2026-10-23',
            valid_to='2026-10-22', status='updated')]))
        state, _ = self.sync(['ONE'])
        self.assertEqual(len(state['changes']), 1)
        self.assertEqual(state['changes'][0]['order_no'], 'OLD')
        self.assertNotIn('pol', state['changes'][0])
        self.assertEqual(Console(self.service.path, {}).snapshot()['changes'], state['changes'])

    def test_client_rejects_incomplete_read_and_unknown_write_fields(self):
        for orders in (None, {}, [dict(self.rows[0], pod='X')]):
            if isinstance(orders, list):
                del orders[0]['pol']
            self.wps.call.side_effect = None
            self.wps.call.return_value = {'ok': True, 'orders': orders}
            with self.assertRaises(RuntimeError):
                self.wps.read()
        self.wps.call.reset_mock()
        for ports in ({'remark': '覆盖'}, {'pod': ''}, {'pod': '=FORMULA()'}):
            with self.assertRaises(ValueError):
                self.wps.update_ports(self.rows[0], ports)
        self.wps.call.assert_not_called()

    def test_cli_preview_and_apply_share_port_rules(self):
        update, update_ports = Mock(), Mock()
        for dry_run in (True, False):
            result = run(self.rows[:1], self.fetch, update, update_ports=update_ports,
                         dry_run=dry_run, year=None, interval=0)
            self.assertEqual(result, 0)
            self.assertEqual(update_ports.call_count, 0 if dry_run else 1)
        update.assert_not_called()
        self.results['ONE']['etd'] = date(2026, 10, 31)
        run(self.rows[:1], self.fetch, update, update_ports=update_ports,
            dry_run=False, year=None, interval=0)
        self.assertEqual(update.call_args.kwargs['ports'], {'pol': 'QINGDAO', 'pod': 'HAMBURG'})


if __name__ == '__main__':
    unittest.main()

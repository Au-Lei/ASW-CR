import unittest
from datetime import date
from unittest.mock import Mock, patch

from etd_sync.dates import needs_update, parse_date, current_status
from etd_sync.evergreen import extract_etd
from etd_sync.__main__ import run
from etd_sync.wps import WpsClient


class SyncTests(unittest.TestCase):
    def test_business_status_priority_and_date_boundaries(self):
        today, original = date(2026, 10, 27), date(2026, 10, 28)
        cases = [
            (date(2026, 10, 26), date(2026, 10, 25), '已完成'),
            (date(2026, 10, 27), date(2026, 10, 26), '托班到下一批次'),
            (date(2026, 10, 28), date(2026, 10, 27), '托班到下一批次'),
            (date(2026, 10, 29), date(2026, 10, 29), 'ETD已变更'),
            (date(2026, 10, 28), date(2026, 10, 28), 'ETD未变更'),
            (date(2026, 10, 27), date(2026, 10, 30), 'ETD已变更'),
        ]
        for latest, valid_to, expected in cases:
            with self.subTest(latest=latest, valid_to=valid_to):
                self.assertEqual(current_status(original, latest, valid_to, today), expected)
        with self.assertRaises(ValueError):
            current_status(original, original, None, today)
        self.assertEqual(current_status(original, date(2026, 10, 26), None, today), '已完成')

    def test_dates(self):
        for raw in ('2026-10-26', 'Oct-26-2026', 'OCT-26-2026 12:00'):
            self.assertEqual(parse_date(raw), date(2026, 10, 26))
        self.assertEqual(parse_date('12.31', 2026), date(2026, 12, 31))
        self.assertEqual(parse_date(46321), date(2026, 10, 26))
        for raw in ('10.26', 10.26, '2026-02-30'):
            with self.assertRaises(ValueError):
                parse_date(raw)

    def test_decisions(self):
        old, new = date(2026, 10, 21), date(2026, 10, 26)
        self.assertTrue(needs_update(old, None, new))
        self.assertFalse(needs_update(old, None, old))
        self.assertFalse(needs_update(old, new, new))
        self.assertTrue(needs_update(old, new, old))
        self.assertTrue(needs_update(date(2026, 12, 31), None, date(2027, 1, 1)))

    def test_no_write_on_failure_duplicate_or_preview(self):
        order = dict(order_no='TEST', original_etd='2026-10-21', latest_etd=None)
        update = Mock()
        failed = Mock(side_effect=ValueError('查询失败'))
        self.assertEqual(run([order], failed, update, dry_run=False, year=None, interval=0), 1)
        fetch = Mock(return_value={'etd': date(2026, 10, 26)})
        self.assertEqual(run([order, order], fetch, update, dry_run=False, year=None, interval=0), 2)
        fetch.assert_not_called()
        run([order], fetch, update, dry_run=True, year=None, interval=0)
        update.assert_not_called()
        run([order], fetch, update, dry_run=False, year=None, interval=0)
        update.assert_called_once_with(order, date(2026, 10, 26))

    def test_parser_fails_closed(self):
        header = '<tr><th colspan="2"></th><th>VGM Hard Copy</th><th>VGM EDI</th><th>Cut Off Date</th><th>Estimated Arrival Date</th><th>Estimated Departure Date</th></tr>'
        row = '<tr><td>Port of Loading</td><td>SHANGHAI</td><td></td><td></td><td></td><td></td><td>Oct-26-2026</td></tr>'
        self.assertEqual(extract_etd('<table>' + header + row + '</table>')['etd'], date(2026, 10, 26))
        for html in ('<table></table>', '<table>' + header + row + row + '</table>',
                     '<table>' + header + row.replace('<td></td>', '', 1) + '</table>',
                     '<table>' + row + '</table>'):
            with self.assertRaises(ValueError):
                extract_etd(html)

    @patch('etd_sync.wps.requests.post')
    def test_wps_status_payload_contract_and_version_check(self, post):
        client = WpsClient('https://www.kdocs.cn/api/v3/ide/file/test/script/test/sync_task', 'test', '工作表1')
        post.return_value.status_code = 200
        post.return_value.json.return_value = {'status': 'finished', 'data': {'result': {'ok': True,
            'orders': [dict(order_no='TEST', original_etd='2026-10-28', latest_etd=None)]}}}
        with self.assertRaisesRegex(RuntimeError, '版本过旧'):
            client.read()
        order = dict(order_no='TEST', original_etd='2026-10-28', latest_etd=None,
                     valid_to='2026-10-30', current_status=None)
        post.return_value.json.return_value = {'status': 'finished', 'data': {'result': {
            'ok': True, 'current_status': 'ETD未变更'}}}
        client.update_status(order, 'ETD未变更')
        argv = post.call_args.kwargs['json']['Context']['argv']
        self.assertEqual(argv['action'], 'update_status')
        self.assertEqual(argv['expected_valid_to'], '2026-10-30')
        self.assertIsNone(argv['expected_status'])
        self.assertNotIn('latest_etd', argv)
        post.return_value.json.return_value = {'status': 'finished', 'data': {'result': {'ok': True}}}
        with self.assertRaisesRegex(RuntimeError, '未确认'):
            client.update(order, date(2026, 10, 29), 'ETD已变更')

    @patch('etd_sync.wps.requests.post')
    def test_wps_response_contract(self, post):
        client = WpsClient('https://www.kdocs.cn/api/v3/ide/file/test/script/test/sync_task', 'test', '工作表1')
        post.return_value.status_code = 200
        post.return_value.json.return_value = {'status': 'finished', 'error': '', 'data': {
            'result': '{"ok":true,"orders":[]}'}}
        self.assertEqual(client.read(), [])
        post.return_value.json.return_value = {'status': 'finished', 'error': 'Failed'}
        with self.assertRaises(RuntimeError):
            client.read()
        post.return_value.json.return_value = {'status': 'finished', 'error': "Cannot read properties of undefined (reading 'Cells')"}
        with self.assertRaisesRegex(RuntimeError, 'WPS_SHEET_NAME'):
            client.read()
        post.return_value.json.return_value = {'status': 'finished', 'error': '表头不匹配：A1=提单号，B1=ETD（原BC）'}
        with self.assertRaisesRegex(RuntimeError, '固定列旧版') as outdated:
            client.read()
        self.assertIn('无需把新表改回旧列顺序', str(outdated.exception))
        post.return_value.json.return_value = {'status': 'finished', 'error': 'test https://secret.example/path'}
        with self.assertRaises(RuntimeError) as caught:
            client.read()
        self.assertNotIn('test', str(caught.exception))
        self.assertNotIn('secret.example', str(caught.exception))
        with self.assertRaises(ValueError):
            WpsClient('https://www.kdocs.cn/l/test', 'test', '工作表1')


if __name__ == '__main__':
    unittest.main()

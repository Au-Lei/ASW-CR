import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from etd_sync.storage import ConsoleStore


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'console.sqlite3'
        self.store = ConsoleStore(self.path, clock=lambda: '2026-10-27T12:00:00+08:00')
        self.job = dict(id='one', mode='sync', status='completed',
                        created_at='2026-10-27T11:00:00+08:00', items=[])

    def tearDown(self):
        self.tmp.cleanup()

    def test_idle_polling_reuses_projection_but_callers_cannot_mutate_cache(self):
        self.store.save_progress(self.job, [{'order_no': 'TEST'}])
        with patch('etd_sync.storage.history_changes', wraps=lambda jobs: []) as project:
            first = self.store.snapshot()
            first['orders'][0]['order_no'] = 'CHANGED'
            first['jobs'][0]['items'].append({'bad': 'value'})
            second = self.store.snapshot()
            self.assertEqual(second['orders'], [{'order_no': 'TEST'}])
            self.assertEqual(second['jobs'][0]['items'], [])
            project.assert_called_once()
            self.store.save_job({**self.job, 'message': 'new'})
            self.assertEqual(self.store.snapshot()['jobs'][0]['message'], 'new')
            self.assertEqual(project.call_count, 2)

    def test_progress_transaction_rolls_back_orders_if_task_save_fails(self):
        self.store.save_progress(self.job, [{'order_no': 'ORIGINAL'}])
        self.store.snapshot()  # Also check cached snapshots are not exposed after rollback.
        with patch.object(self.store, '_write_job', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.save_progress({**self.job, 'status': 'failed'}, [{'order_no': 'NEW'}])
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot['orders'], [{'order_no': 'ORIGINAL'}])
        self.assertEqual(snapshot['jobs'][0]['status'], 'completed')

    def test_legacy_database_recovers_running_task_without_schema_migration(self):
        # Use the original two-table JSON format, bypassing the new store entirely.
        item = dict(order_no='TEST', status='querying')
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO jobs VALUES (?,?)',
                       ('old', json.dumps({**self.job, 'id': 'old', 'status': 'running', 'items': [item]})))
            db.execute('INSERT INTO state VALUES (1,?)', (json.dumps([item]),))
        restored = ConsoleStore(self.path, clock=lambda: '2026-10-27T12:00:00+08:00')
        snapshot = restored.snapshot()
        self.assertEqual(snapshot['jobs'][0]['status'], 'interrupted')
        self.assertEqual(snapshot['jobs'][0]['items'][0]['status'], 'interrupted')
        self.assertEqual(snapshot['orders'][0]['status'], 'interrupted')
        with sqlite3.connect(self.path) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {'jobs', 'state'})

    def test_order_save_and_compatibility_db_access_invalidate_cache(self):
        self.assertEqual(self.store.snapshot()['orders'], [])
        self.store.save_orders([{'order_no': 'ONE'}])
        self.assertEqual(self.store.snapshot()['orders'], [{'order_no': 'ONE'}])
        with self.store.db() as db:
            db.execute('UPDATE state SET payload=? WHERE id=1', (json.dumps([{'order_no': 'TWO'}]),))
        self.assertEqual(self.store.snapshot()['orders'], [{'order_no': 'TWO'}])


if __name__ == '__main__':
    unittest.main()

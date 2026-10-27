"""SQLite journal, restart recovery and cached snapshots for one service process."""

import copy
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .orders import history_changes


class ConsoleStore:
    def __init__(self, path, clock):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._snapshot = None
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            interrupted = {}
            for row in db.execute('SELECT id, payload FROM jobs').fetchall():
                job = json.loads(row['payload'])
                if job['status'] != 'running':
                    continue
                job.update(status='interrupted', finished_at=clock(),
                           message='服务重启，同步已中断；请重新同步确认 WPS 结果')
                for item in job['items']:
                    if item['status'] in ('waiting', 'querying'):
                        item.update(status='interrupted', processed_at=clock(),
                                    message='任务中断，结果未确认，请重新读取 WPS')
                        interrupted[item['order_no']] = item
                db.execute('UPDATE jobs SET payload=? WHERE id=?',
                           (json.dumps(job, ensure_ascii=False), row['id']))
            orders = self._read_orders(db)
            if interrupted and orders:
                for order in orders:
                    if order['order_no'] in interrupted:
                        order.update(status='interrupted', message=interrupted[order['order_no']]['message'])
                self._write_orders(db, orders)

    @contextmanager
    def db(self):
        # Serialize writes with snapshot loading so cache invalidation cannot race.
        with self._lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                # Also invalidate on failed writes or direct compatibility access.
                self._snapshot = None
                db.close()

    @staticmethod
    def _write_job(db, job):
        db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)',
                   (job['id'], json.dumps(job, ensure_ascii=False)))

    @staticmethod
    def _write_orders(db, orders):
        db.execute('INSERT OR REPLACE INTO state VALUES (1,?)',
                   (json.dumps(orders, ensure_ascii=False),))

    @staticmethod
    def _read_orders(db):
        row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
        return json.loads(row['payload']) if row else []

    def load_orders(self):
        with self.db() as db:
            return self._read_orders(db)

    def save_job(self, job):
        with self.db() as db:
            self._write_job(db, job)

    def save_orders(self, orders):
        with self.db() as db:
            self._write_orders(db, orders)

    def save_progress(self, job, orders):
        """Commit row results and task progress together, or roll both back."""
        with self.db() as db:
            self._write_orders(db, orders)
            self._write_job(db, job)

    def snapshot(self):
        with self._lock:
            if self._snapshot is None:
                with self.db() as db:
                    orders = self._read_orders(db)
                    jobs = [json.loads(row['payload']) for row in
                            db.execute('SELECT payload FROM jobs ORDER BY rowid DESC')]
                jobs.sort(key=lambda job: job['created_at'], reverse=True)
                self._snapshot = {'orders': orders, 'jobs': jobs[:30], 'changes': history_changes(jobs)}
            # Never expose mutable cached state to callers or workers.
            return copy.deepcopy(self._snapshot)

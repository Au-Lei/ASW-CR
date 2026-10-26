"""Local web console. One process owns the SQLite journal and background worker."""
import argparse
import asyncio
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from .dates import needs_update, parse_date
from .batch import query_batch
from .evergreen import EvergreenClient
from .wps import WpsClient

ROOT = Path(__file__).resolve().parent.parent


def now():
    # Fixed offset avoids an optional tzdata dependency on Windows.
    from datetime import timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


class Console:
    def __init__(self, path, config, wps_factory=None, fetch_factory=None):
        self.path, self.config = Path(path), config
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.wps_factory = wps_factory or (lambda: WpsClient(config.get('WPS_WEBHOOK_URL', ''),
            config.get('WPS_API_TOKEN', ''), config.get('WPS_SHEET_NAME', '工作表1')))
        self.fetch_factory = fetch_factory
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            # A restart must never present an abandoned task as still running.
            interrupted = {}
            for row in db.execute('SELECT id, payload FROM jobs').fetchall():
                job = json.loads(row['payload'])
                if job['status'] == 'running':
                    job.update(status='interrupted', finished_at=now(), message='服务重启，同步已中断；请重新同步确认 WPS 结果')
                    for item in job['items']:
                        if item['status'] in ('waiting', 'querying'):
                            item.update(status='interrupted', processed_at=now(), message='任务中断，结果未确认，请重新读取 WPS')
                            interrupted[item['order_no']] = item
                    db.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job, ensure_ascii=False), row['id']))
            state = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
            if interrupted and state:
                orders = json.loads(state['payload'])
                for order in orders:
                    if order['order_no'] in interrupted:
                        order.update(status='interrupted', message=interrupted[order['order_no']]['message'])
                db.execute('UPDATE state SET payload=? WHERE id=1', (json.dumps(orders, ensure_ascii=False),))

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_job(self, job):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (job['id'], json.dumps(job, ensure_ascii=False)))

    def save_orders(self, orders):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (json.dumps(orders, ensure_ascii=False),))

    def snapshot(self):
        with self.db() as db:
            state = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
            jobs = [json.loads(row['payload']) for row in db.execute('SELECT payload FROM jobs ORDER BY rowid DESC LIMIT 30')]
        # INSERT OR REPLACE moves a row, so sort explicitly by creation timestamp/id order.
        jobs.sort(key=lambda job: job['created_at'], reverse=True)
        return {'orders': json.loads(state['payload']) if state else [], 'jobs': jobs,
                'sheet': self.config.get('WPS_SHEET_NAME', '工作表1'),
                'configured': bool(self.config.get('WPS_WEBHOOK_URL') and self.config.get('WPS_API_TOKEN'))}

    def error(self, exc):
        name = type(exc).__name__
        if name == 'TimeoutError':
            return '官网响应超时，请稍后重试；必要时人工查询长荣官网'
        if not isinstance(exc, (ValueError, RuntimeError)):
            return '操作失败（' + name + '），请联系管理员检查网络和浏览器环境'
        message = str(exc)
        for key in ('WPS_API_TOKEN', 'WPS_WEBHOOK_URL'):
            if self.config.get(key):
                message = message.replace(self.config[key], '[已隐藏]')
        return re.sub(r'https?://\S+', '[地址已隐藏]', message)[:400]

    def start(self, mode):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('已有任务正在运行，请等待完成')
        job = {'id': uuid.uuid4().hex, 'mode': mode, 'status': 'running', 'created_at': now(),
               'finished_at': None, 'total': 0, 'processed': 0, 'items': [], 'message': '正在读取 WPS 订单…'}
        try:
            self.save_job(job)
            thread = threading.Thread(target=self.execute, args=(job,), daemon=True)
            thread.start()
        except Exception:
            self.lock.release()
            raise
        return job['id']

    def execute(self, job):
        started = time.perf_counter()
        orders = None
        try:
            year = int(self.config['DATE_YEAR']) if self.config.get('DATE_YEAR') else None
            interval = float(self.config.get('QUERY_INTERVAL_SECONDS', '1'))
            concurrency = int(self.config.get('QUERY_CONCURRENCY', '2'))
            if not math.isfinite(interval) or interval < 0 or not 1 <= concurrency <= 3:
                raise ValueError('查询间隔须为非负有限数，并发数须为 1–3')
            job.update(concurrency=concurrency, interval_seconds=interval)
            client = self.wps_factory()
            previous = {str(o['order_no']): o for o in self.snapshot()['orders']}
            raw = client.read()
            if not isinstance(raw, list):
                raise ValueError('WPS 订单结果格式异常')
            orders = []
            for order in raw:
                number = str(order['order_no']).strip()
                old = previous.get(number, {})
                changed = old and (old.get('original_etd') != order['original_etd'] or
                                   old.get('latest_etd') != order['latest_etd'])
                orders.append({**order, 'order_no': number, 'last_checked': old.get('last_checked'),
                               'status': 'unqueried' if changed else old.get('status', 'unqueried'),
                               'message': '表格数据已变化，请重新同步' if changed else old.get('message', ''),
                               'pol': old.get('pol', '')})
            self.save_orders(orders)
            job['total'] = len(orders)
            if job['mode'] == 'read':
                job.update(status='completed', message=f'已从 WPS 读取 {len(orders)} 票订单')
                return
            job['items'] = [{**order, 'before_etd': order['latest_etd'], 'queried_etd': None,
                             'status': 'waiting', 'message': '等待查询'} for order in orders]
            self.save_job(job)
            asyncio.run(self.sync_orders(job, orders, client, year, interval, concurrency))
            failed = sum(item['status'] == 'failed' for item in job['items'])
            job.update(status='partial' if failed else 'completed', message=
                       f'同步完成，{failed} 票未成功，请查看异常明细' if failed else '同步完成，所有订单已核对')
        except Exception as exc:
            job.update(status='failed', message=self.error(exc))
            for index, item in enumerate(job['items']):
                if item['status'] in ('waiting', 'querying'):
                    item.update(status='failed', processed_at=now(), failure_stage='query',
                                message='任务异常结束，请重新读取 WPS 确认。' + self.error(exc))
                    job['processed'] += 1
                    if orders is not None:
                        orders[index].update(status='failed', message=item['message'])
            if orders is not None:
                self.save_orders(orders)
        finally:
            job['finished_at'] = now()
            job['duration_seconds'] = round(time.perf_counter() - started, 2)
            try:
                self.save_job(job)
            finally:
                self.lock.release()

    async def sync_orders(self, job, orders, client, year, interval, concurrency):
        counts = Counter(o['order_no'] for o in orders)
        dates, entries = {}, []

        def on_start(index):
            item = job['items'][index]
            item.update(status='querying', attempted_at=now(), message='正在查询官网')
            job['message'] = f"正在同步：已完成 {job['processed']}/{len(orders)} 票，最多 {concurrency} 票同时查询"
            self.save_job(job)

        async def on_result(index, result, error, query_seconds):
            order, item = orders[index], job['items'][index]
            stage = 'query'
            item['query_seconds'] = round(query_seconds, 2)
            try:
                if error:
                    raise error
                latest = result['etd']
                if latest is None:
                    raise ValueError('官网没有返回有效 ETD')
                item.update(queried_etd=latest.isoformat(), pol=result.get('pol', ''))
                order.update(pol=item['pol'], last_checked=now())
                original, saved = dates[index]
                if needs_update(original, saved, latest):
                    stage = 'write'
                    # Only this result handler writes; no concurrent mutations in WPS.
                    # Network I/O runs off the event loop, allowing other pages to load.
                    await asyncio.to_thread(client.update, order, latest)
                    order['latest_etd'] = latest.isoformat()
                    item.update(status='updated', written_at=now(), message='已写入 WPS 并验证')
                else:
                    item.update(status='unchanged', message='日期一致，无需写入')
            except Exception as exc:
                message = self.error(exc)
                if stage == 'write':
                    message = '写入结果待确认，请重新读取 WPS。' + message
                item.update(status='failed', failure_stage=stage, message=message)
            item['processed_at'] = now()
            item['last_checked'] = order.get('last_checked')
            order.update(status=item['status'], message=item['message'])
            job['processed'] += 1
            job['message'] = f"正在同步：已完成 {job['processed']}/{len(orders)} 票，最多 {concurrency} 票同时查询"
            self.save_orders(orders)
            self.save_job(job)

        # Reject bad/duplicate rows before issuing any browser requests.
        for index, order in enumerate(orders):
            try:
                if counts[order['order_no']] != 1:
                    raise ValueError('单号重复，请在 WPS 核对后重新同步')
                original = parse_date(order['original_etd'], year)
                saved = parse_date(order['latest_etd'], year)
                if original is None:
                    raise ValueError('原始 ETD 为空，请在 WPS 填写完整日期')
                dates[index] = original, saved
                entries.append((index, order['order_no']))
            except Exception as exc:
                await on_result(index, None, exc, 0)
        if not entries:
            return
        if self.fetch_factory:
            fetch = self.fetch_factory()
            async def injected_fetch(number, lane):
                return await asyncio.to_thread(fetch, number)
            await query_batch(entries, injected_fetch, on_start, on_result,
                              concurrency=concurrency, interval=interval)
        else:
            browser = EvergreenClient(headless=True, number_type=self.config.get('EVERGREEN_NUMBER_TYPE', 'booking'))
            async with browser.session(min(concurrency, len(entries))) as session:
                await query_batch(entries, session.fetch, on_start, on_result,
                                  concurrency=concurrency, interval=interval)


def create_app(config=None, console=None):
    load_dotenv(ROOT / '.env')
    config = dict(os.environ) if config is None else config
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['MAX_CONTENT_LENGTH'] = 4096
    app.config['TRUSTED_HOSTS'] = ['127.0.0.1', 'localhost', '[::1]']
    csrf = secrets.token_urlsafe(32)
    service = console or Console(ROOT / 'data' / 'console.sqlite3', config)
    app.extensions['console'] = service

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.get('/')
    def index():
        return render_template('index.html', csrf=csrf)

    @app.get('/api/state')
    def state():
        return jsonify(service.snapshot())

    @app.post('/api/jobs')
    def start():
        if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), csrf):
            return jsonify(error='页面已过期，请刷新后重试'), 403
        mode = (request.get_json(silent=True) or {}).get('mode')
        if mode not in ('read', 'sync'):
            return jsonify(error='未知操作'), 400
        try:
            return jsonify(id=service.start(mode)), 202
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409

    return app


def main():
    parser = argparse.ArgumentParser(description='长荣船期同步网页控制台')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1', help='容器内部可设为 0.0.0.0，主机发布仍限制本机')
    args = parser.parse_args()
    from waitress import serve
    print(f'管理界面：http://127.0.0.1:{args.port} （关闭窗口即停止服务）', flush=True)
    serve(create_app(), host=args.host, port=args.port, threads=6)


if __name__ == '__main__':
    main()

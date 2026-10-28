"""Background task ownership and serialized WPS result processing."""
import asyncio
import math
import re
import threading
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from .batch import query_batch
from .dates import needs_update, parse_date, current_status
from .evergreen import EvergreenClient
from .orders import normalize_targets, reconcile_orders, target_indices, port_changes
from .storage import ConsoleStore
from .wps import WpsClient


def now():
    # Fixed offset avoids an optional tzdata dependency on Windows.
    from datetime import timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


class Console:
    def __init__(self, path, config, wps_factory=None, fetch_factory=None):
        self.path, self.config = Path(path), config
        self.lock = threading.Lock()
        self.wps_factory = wps_factory or (lambda: WpsClient(config.get('WPS_WEBHOOK_URL', ''),
            config.get('WPS_API_TOKEN', ''), config.get('WPS_SHEET_NAME', '工作表1')))
        self.fetch_factory = fetch_factory
        self.store = ConsoleStore(self.path, clock=lambda: now())

    def db(self):
        return self.store.db()

    def save_job(self, job):
        self.store.save_job(job)

    def save_orders(self, orders):
        self.store.save_orders(orders)

    def snapshot(self):
        return {**self.store.snapshot(), 'sheet': self.config.get('WPS_SHEET_NAME', '工作表1'),
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

    def start(self, mode, order_nos=None):
        order_nos = normalize_targets(mode, order_nos)
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('已有任务正在运行，请等待完成')
        job = {'id': uuid.uuid4().hex, 'mode': mode, 'status': 'running', 'created_at': now(),
               'finished_at': None, 'total': 0, 'processed': 0, 'items': [], 'message': '正在读取 WPS 订单…'}
        job.update(scope='selected' if order_nos is not None else 'all', order_nos=order_nos)
        saved = False
        try:
            self.save_job(job)
            saved = True
            thread = threading.Thread(target=self.execute, args=(job,), daemon=True)
            thread.start()
        except Exception as exc:
            try:
                if saved:
                    job.update(status='failed', finished_at=now(),
                               message='后台任务未能启动。' + self.error(exc))
                    self.save_job(job)
            finally:
                self.lock.release()
            raise
        return job['id']

    def execute(self, job):
        started = time.perf_counter()
        orders = None
        indices = []
        try:
            year = int(self.config['DATE_YEAR']) if self.config.get('DATE_YEAR') else None
            interval = float(self.config.get('QUERY_INTERVAL_SECONDS', '1'))
            concurrency = int(self.config.get('QUERY_CONCURRENCY', '2'))
            if not math.isfinite(interval) or interval < 0 or not 1 <= concurrency <= 3:
                raise ValueError('查询间隔须为非负有限数，并发数须为 1–3')
            job.update(concurrency=concurrency, interval_seconds=interval, date_year=year)
            client = self.wps_factory()
            orders = reconcile_orders(client.read(), self.store.load_orders())
            self.save_orders(orders)
            job['total'] = len(orders) if job['mode'] == 'read' else 0
            if job['mode'] == 'read':
                job.update(status='completed', message=f'已从 WPS 读取 {len(orders)} 票订单')
                return
            indices = target_indices(orders, job.get('order_nos'))
            job['total'] = len(indices)
            job['items'] = [{**orders[i], 'before_etd': orders[i]['latest_etd'], 'queried_etd': None,
                             'status': 'waiting', 'message': '等待查询', 'warnings': [],
                             'ports_updated': [], 'ports_written_at': None, 'failure_stage': None,
                             'queried_pol': None, 'queried_pod': None,
                             'pol_raw': None, 'pod_raw': None} for i in indices]
            self.save_job(job)
            asyncio.run(self.sync_orders(job, orders, client, year, interval, concurrency, indices))
            failed = sum(item['status'] == 'failed' for item in job['items'])
            job.update(etd_updated_count=sum(item['status'] == 'updated' for item in job['items']),
                       ports_updated_count=sum(bool(item.get('ports_updated')) for item in job['items']),
                       warning_count=sum(bool(item.get('warnings')) for item in job['items']))
            summary = (f"ETD 更新 {job['etd_updated_count']} 票，港口更新 {job['ports_updated_count']} 票"
                       f"，{job['warning_count']} 票有提示")
            job.update(status='partial' if failed else 'completed', message=
                       (f'同步完成，{failed} 票未成功，请查看异常明细' if failed else
                        f"同步完成，本次 {job['total']} 票订单已核对") + '；' + summary)
        except Exception as exc:
            job.update(status='failed', message=self.error(exc))
            for index, item in enumerate(job['items']):
                if item['status'] in ('waiting', 'querying'):
                    item.update(status='failed', processed_at=now(), failure_stage='query',
                                message='任务异常结束，请重新读取 WPS 确认。' + self.error(exc))
                    job['processed'] += 1
                    if orders is not None:
                        orders[indices[index]].update(status='failed', message=item['message'])
            if orders is not None:
                self.save_orders(orders)
        finally:
            job['finished_at'] = now()
            job['duration_seconds'] = round(time.perf_counter() - started, 2)
            try:
                self.save_job(job)
            finally:
                self.lock.release()

    async def sync_orders(self, job, orders, client, year, interval, concurrency, indices=None):
        indices = list(range(len(orders))) if indices is None else indices
        items = dict(zip(indices, job['items']))
        counts = Counter(o['order_no'] for o in orders)
        dates, entries = {}, []

        def update_progress():
            job['message'] = f"正在同步：已完成 {job['processed']}/{job['total']} 票，最多 {concurrency} 票同时查询"

        def on_start(index):
            item = items[index]
            item.update(status='querying', attempted_at=now(), message='正在查询官网')
            update_progress()
            self.save_job(job)

        async def on_result(index, result, error, query_seconds):
            order, item = orders[index], items[index]
            stage = 'query'
            item['query_seconds'] = round(query_seconds, 2)
            try:
                if error:
                    raise error
                latest = result['etd']
                if latest is None:
                    raise ValueError('官网没有返回有效 ETD')
                item.update(queried_etd=latest.isoformat(), queried_pol=result.get('pol'),
                            queried_pod=result.get('pod'), pol_raw=result.get('pol_raw'),
                            pod_raw=result.get('pod_raw'))
                order['last_checked'] = now()
                ports, warnings = port_changes(order, result)
                item['warnings'] = warnings
                port_options = {'ports': ports} if ports else {}
                # Legacy sheets can still display the queried loading port locally.
                if not order.get('ports_enabled') and result.get('pol'):
                    order['pol'] = item['pol'] = result['pol']
                original, saved = dates[index]
                business_status = None
                if 'current_status' in order:
                    today = datetime.fromisoformat(now()).date()
                    business_status = current_status(original, latest,
                        None if today > latest else parse_date(order.get('valid_to'), year), today)
                if needs_update(original, saved, latest):
                    stage = 'write'
                    # Only this result handler writes; no concurrent mutations in WPS.
                    # Network I/O runs off the event loop, allowing other pages to load.
                    if business_status is None:
                        await asyncio.to_thread(client.update, order, latest, **port_options)
                    else:
                        await asyncio.to_thread(client.update, order, latest, current_status=business_status, **port_options)
                    order['latest_etd'] = latest.isoformat()
                    item.update(status='updated', written_at=now(), message='已写入 WPS 并验证')
                else:
                    if ports:
                        stage = 'write'
                        options = {} if business_status is None else {'current_status': business_status}
                        await asyncio.to_thread(client.update_ports, order, ports, **options)
                        item.update(status='unchanged', message='ETD 无需变更，港口已写回并验证')
                        if business_status is not None and business_status != order.get('current_status'):
                            item['status_written_at'] = now()
                    elif business_status is not None and business_status != order.get('current_status'):
                        stage = 'write'
                        await asyncio.to_thread(client.update_status, order, business_status)
                        item.update(status='unchanged', message='ETD 无需变更，当前状态已写回并验证', status_written_at=now())
                    else:
                        item.update(status='unchanged', message='日期一致，无需写入')
                if ports:
                    order.update(ports)
                    item.update(ports, ports_updated=list(ports), ports_written_at=now())
                    if item['status'] == 'updated':
                        item['message'] = 'ETD 与港口已写入 WPS 并验证'
                if business_status is not None:
                    order['current_status'] = item['current_status'] = business_status
            except Exception as exc:
                message = self.error(exc)
                if stage == 'write':
                    message = '写入结果待确认，请重新读取 WPS。' + message
                item.update(status='failed', failure_stage=stage, message=message)
            if item.get('warnings'):
                item['message'] += '；' + '；'.join(item['warnings'])
            item['processed_at'] = now()
            item['last_checked'] = order.get('last_checked')
            order.update(status=item['status'], message=item['message'])
            order.update({key: item.get(key) for key in ('before_etd', 'queried_etd', 'failure_stage',
                'queried_pol', 'queried_pod', 'pol_raw', 'pod_raw', 'warnings', 'ports_updated', 'ports_written_at')})
            job['processed'] += 1
            update_progress()
            self.store.save_progress(job, orders)

        # Reject bad/duplicate rows before issuing any browser requests.
        for index in indices:
            order = orders[index]
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

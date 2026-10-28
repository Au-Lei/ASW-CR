"""Packaged offline smoke check: real Chromium + local UI, never WPS or Evergreen."""
import sys
import tempfile
from datetime import date
from pathlib import Path

from .desktop_runtime import InstanceLock, LocalServer, existing_url
from .service import Console


class DemoWps:
    def __init__(self):
        self.order = dict(order_no='PACKAGED-DEMO', original_etd='2026-10-21',
                          latest_etd=None, valid_to='2026-10-25', current_status=None,
                          pol=None, pod=None, remark='保留人工备注')

    def read(self):
        return [dict(self.order)]

    def update(self, order, latest, current_status=None, *, ports=None):
        self.order.update(latest_etd=latest.isoformat(), current_status=current_status)
        self.order.update(ports or {})

    def update_status(self, order, current_status):
        self.order['current_status'] = current_status

    def update_ports(self, order, ports, current_status=None):
        self.order.update(ports)
        if current_status is not None:
            self.order['current_status'] = current_status


def self_test():
    from playwright.sync_api import sync_playwright, expect
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        config = {'WPS_SHEET_NAME': '离线安装包自检', 'QUERY_INTERVAL_SECONDS': '0'}
        fake = DemoWps()
        console = Console(Path(directory) / 'test.sqlite3', config, wps_factory=lambda: fake,
                          fetch_factory=lambda: lambda n: {'etd': date(2026, 10, 26),
                                                                         'pol': 'QINGDAO', 'pod': 'HAMBURG'})
        server = LocalServer(config, console=console)
        lock = InstanceLock(Path(directory) / 'desktop.lock')
        try:
            assert lock.acquire()
            assert not InstanceLock(Path(directory) / 'desktop.lock').acquire()
            server.start()
            runtime = Path(directory) / 'instance.json'
            server.publish(runtime)
            assert existing_url(runtime) == server.url
            checks.append('single-instance-identity')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('console', lambda message: errors.append(message.text)
                            if message.type == 'error' else None)
                    with page.expect_response(lambda response: response.url.endswith('/api/state')
                                              and response.status == 200):
                        page.goto(server.url)
                    page.locator('#read-button').click()
                    expect(page.locator('#orders-body tr')).to_have_count(1)
                    page.locator('#sync-button').click()
                    expect(page.locator('#stat-updated')).to_have_text('1', timeout=15000)
                    expect(page.locator('#task-title')).to_contain_text('同步数据 · 已完成')
                    page.locator('[data-page=history]').click()
                    expect(page.locator('#changes-body tr')).to_have_count(1)
                    assert not errors, errors
                    assert fake.order['latest_etd'] == '2026-10-26'
                    assert fake.order['pol'] == 'QINGDAO' and fake.order['pod'] == 'HAMBURG'
                    expect(page.locator('#changes-body')).to_contain_text('QINGDAO')
                    expect(page.locator('#changes-body')).to_contain_text('保留人工备注')
                    page.locator('[data-page=realtime]').click()
                    page.locator('#search').fill('hamburg')
                    expect(page.locator('#orders-body tr')).to_have_count(1)
                    page.locator('#search').fill('保留人工备注')
                    expect(page.locator('#orders-body tr')).to_have_count(1)
                    page.locator('#search').fill('')
                    # Same date with missing ports must perform a port-only write.
                    fake.order.update(pol=None, pod=None)
                    page.locator('#sync-button').click()
                    expect(page.locator('#stat-updated')).to_have_text('0', timeout=15000)
                    expect(page.locator('#task-title')).to_contain_text('同步数据 · 已完成')
                    assert fake.order['pol'] == 'QINGDAO' and fake.order['pod'] == 'HAMBURG'
                    assert fake.order['remark'] == '保留人工备注'
                    assert console.snapshot()['jobs'][0]['ports_updated_count'] == 1
                    assert len(console.snapshot()['changes']) == 1
                    checks.extend(['port-writes', 'port-only-sync', 'port-remark-search', 'history-snapshots'])
                    checks.extend(['bundled-chromium', 'templates-css-es-modules', 'offline-sync', 'history', 'sqlite'])
                except Exception as exc:
                    raise RuntimeError(f'{exc}\nBrowser errors: {errors}\n'
                                       f'Offline state: {console.snapshot()}') from exc
                finally:
                    browser.close()
        finally:
            server.close()
            lock.close()
    if sys.platform == 'win32':
        import tkinter as tk
        import pystray
        from tkinter import ttk
        from .desktop import tray_image
        from .desktop_config import DEFAULTS, configure, save_config
        root = tk.Tk()
        root.withdraw()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            save_config(path, {**DEFAULTS, 'WPS_API_TOKEN': 'offline-test', 'DATE_YEAR': '2026',
                'WPS_WEBHOOK_URL': 'https://www.kdocs.cn/api/v3/ide/file/demo/script/demo/sync_task'})

            def submit(widget):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Button) and child.cget('text') == '保存配置':
                        child.invoke()
                        return True
                    if submit(child):
                        return True
                return False

            root.after(200, lambda: submit(root))
            timeout = root.after(5000, root.destroy)
            result = configure(root, path)
            assert result and result['WPS_API_TOKEN'] == 'offline-test'
            root.after_cancel(timeout)
            root.destroy()
        assert pystray.Icon and tray_image().size == (64, 64)
        checks.extend(['first-run-config-dialog', 'windows-tray-backend'])
    return {'ok': True, 'checks': checks, 'platform': sys.platform,
            'frozen': bool(getattr(sys, 'frozen', False))}

"""Offline UI integration check. Never calls WPS or Evergreen."""
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.runtime'))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from etd_sync.web import Console, create_app


class FakeWps:
    def __init__(self):
        self.orders = [
            dict(order_no='DEMO-UPDATED', original_etd='2026-10-21', latest_etd='2026-10-25'),
            dict(order_no='DEMO-SAME', original_etd='2026-10-21', latest_etd=None),
            dict(order_no='DEMO-FAILED', original_etd='2026-10-21', latest_etd='2026-10-25')]

    def read(self):
        time.sleep(.2)
        return [dict(order) for order in self.orders]

    def update(self, order, latest):
        next(row for row in self.orders if row['order_no'] == order['order_no'])['latest_etd'] = latest.isoformat()


def fetch(number):
    time.sleep(.3)
    if number == 'DEMO-FAILED':
        raise ValueError('官网暂未返回有效 ETD，请稍后重试')
    return {'etd': date(2026, 10, 26) if number == 'DEMO-UPDATED' else date(2026, 10, 21), 'pol': 'QINGDAO, CHINA (CN)'}


if __name__ == '__main__':
    captures = ROOT / '.impeccable' / 'review'
    captures.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        wps = FakeWps()
        config = {'WPS_SHEET_NAME': '工作表1 · 离线演示', 'WPS_WEBHOOK_URL': 'demo',
                  'WPS_API_TOKEN': 'demo', 'QUERY_INTERVAL_SECONDS': '0'}
        console = Console(Path(directory) / 'test.sqlite3', config,
                          wps_factory=lambda: wps, fetch_factory=lambda: fetch)
        server = make_server('127.0.0.1', 8001, create_app(config, console=console), threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width':1440, 'height':1000}, device_scale_factor=1)
                errors = []
                page.on('pageerror', lambda exc: errors.append(str(exc)))
                page.goto('http://127.0.0.1:8001')
                expect(page.locator('#connection')).to_contain_text('已配置')
                page.screenshot(path=str(captures / 'empty.png'), full_page=True, animations='disabled')
                page.locator('#read-button').click()
                expect(page.locator('#orders-body tr')).to_have_count(3)
                assert page.locator('#stat-total').inner_text() == '3'
                page.locator('#sync-button').click()
                expect(page.locator('#sync-button')).to_be_disabled()
                expect(page.locator('#task-title')).to_contain_text('部分失败', timeout=15000)
                assert page.locator('#stat-updated').inner_text() == '1'
                assert page.locator('#stat-unchanged').inner_text() == '1'
                assert page.locator('#stat-failed').inner_text() == '1'
                page.locator('[data-filter=updated]').click()
                assert page.locator('#orders-body tr').count() == 1
                assert '2026-10-26' in page.locator('#orders-body').inner_text()
                page.locator('[data-filter=failed]').click()
                assert '请稍后重试' in page.locator('#orders-body').inner_text()
                page.locator('[data-filter=all]').click()
                page.locator('#search').fill('NO-MATCH')
                assert page.locator('#empty').is_visible()
                page.locator('#search').fill('')
                page.screenshot(path=str(captures / 'desktop.png'), full_page=True, animations='disabled')
                page.locator('[data-page=history]').click()
                expect(page.locator('#changes-body tr')).to_have_count(1)
                page.screenshot(path=str(captures / 'history.png'), full_page=True, animations='disabled')
                page.locator('#history-list button').first.click()
                assert page.locator('#orders-title').inner_text() == '同步明细'
                page.locator('#back-button').click()
                page.locator('[data-page=logs]').click()
                expect(page.locator('#terminal-logs')).to_contain_text('已写入 WPS 并验证')
                page.screenshot(path=str(captures / 'logs.png'), full_page=True, animations='disabled')
                page.locator('[data-page=realtime]').click()
                page.set_viewport_size({'width':390,'height':844})
                page.evaluate('window.scrollTo(0,0)')
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path=str(captures / 'mobile.png'), full_page=True, animations='disabled')
                assert not errors, errors
                browser.close()
                print('Browser UI checks passed: read, sync, progress, statistics, filters, errors, search, history, mobile.')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

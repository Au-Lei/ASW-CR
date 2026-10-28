"""Offline UI integration check. Never calls WPS or Evergreen."""
import sys
import json
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.runtime'))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from etd_sync.web import Console, create_app


HISTORY_NOTE = '船公司甩货，不影响价格\n' + '长备注内容 ' * 25 + '\n<img src=x onerror="window.badNote=true">'


class FakeWps:
    def __init__(self):
        self.orders = [
            dict(order_no='DEMO-UPDATED', original_etd='2026-10-21', latest_etd='2026-10-25', valid_to='2026-10-25', current_status=None,
                 pol='OLD LOADING', pod='OLD DISCHARGE', remark=HISTORY_NOTE),
            dict(order_no='DEMO-SAME', original_etd='2026-10-21', latest_etd=None,
                 pol='OLD PORT', pod='\u00a0KEEP DESTINATION', remark='人工备注'),
            dict(order_no='DEMO-FAILED', original_etd='2026-10-21', latest_etd='2026-10-25',
                 pol='LONGPORT' * 25, pod=None, remark=None)]

    def read(self):
        time.sleep(.2)
        return [dict(order) for order in self.orders]

    def update(self, order, latest, current_status=None, *, ports=None):
        next(row for row in self.orders if row['order_no'] == order['order_no'])['latest_etd'] = latest.isoformat()
        if ports:
            self.update_ports(order, ports)
        if current_status is not None:
            self.update_status(order, current_status)

    def update_status(self, order, current_status):
        next(row for row in self.orders if row['order_no'] == order['order_no'])['current_status'] = current_status

    def update_ports(self, order, ports, current_status=None):
        row = next(row for row in self.orders if row['order_no'] == order['order_no'])
        row.update(ports)
        if current_status is not None:
            row['current_status'] = current_status


def fetch(number):
    time.sleep(.3)
    if number == 'DEMO-FAILED':
        raise ValueError('官网暂未返回有效 ETD，请稍后重试')
    return {'etd': date(2026, 10, 26) if number == 'DEMO-UPDATED' else date(2026, 10, 21), 'pol': 'QINGDAO, CHINA (CN)', 'pod': 'NHAVA SHEVA' if number == 'DEMO-UPDATED' else None}


if __name__ == '__main__':
    captures = ROOT / '.impeccable' / 'review'
    captures.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory, patch('etd_sync.service.now', return_value='2026-10-27T12:00:00+08:00'):
        wps = FakeWps()
        config = {'WPS_SHEET_NAME': '工作表1 · 离线演示', 'WPS_WEBHOOK_URL': 'demo',
                  'WPS_API_TOKEN': 'demo', 'QUERY_INTERVAL_SECONDS': '0'}
        console = Console(Path(directory) / 'test.sqlite3', config,
                          wps_factory=lambda: wps, fetch_factory=lambda: fetch)
        server = make_server('127.0.0.1', 0, create_app(config, console=console), threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width':1440, 'height':1000}, device_scale_factor=1)
                errors = []
                submissions = []
                page.on('pageerror', lambda exc: errors.append(str(exc)))
                page.on('request', lambda req: submissions.append(req.post_data_json)
                        if req.method == 'POST' and req.url.endswith('/api/jobs') else None)
                page.goto(f'http://127.0.0.1:{server.server_port}')
                expect(page.locator('#connection')).to_contain_text('已配置')
                page.screenshot(path=str(captures / 'empty.png'), full_page=True, animations='disabled')
                page.locator('#read-button').click()
                expect(page.locator('#orders-body tr')).to_have_count(3)
                assert page.locator('#stat-total').inner_text() == '3'
                assert page.locator('.orders-table th').all_text_contents() == [
                    '', '提单 / 订舱号', '起运港', '目的港', 'ETD（原BC）', 'Valid to',
                    'ETD表格现值 / 官网查询', '当前状态', '备注', '同步结果', '最近成功查询', '操作']
                first=page.locator('#orders-body tr').filter(has_text='DEMO-UPDATED')
                expect(first.locator('td').nth(2)).to_have_text('OLD LOADING')
                expect(first.locator('td').nth(3)).to_have_text('OLD DISCHARGE')
                expect(first.locator('td').nth(6)).to_have_text('2026-10-25')
                expect(first.locator('.remark-cell img')).to_have_count(0)
                first.locator('.remark-cell summary').click()
                expect(first.locator('.remark-content')).to_have_text(HISTORY_NOTE)
                page.locator('#search').fill('OLD LOADING')
                expect(page.locator('#orders-body tr')).to_have_count(1)
                expect(page.locator('#orders-body details')).to_have_attribute('open','')
                summary=page.locator('#orders-body summary')
                summary.focus()
                summary.press('Enter')
                expect(page.locator('#orders-body details')).not_to_have_attribute('open','')
                summary.press('Enter')
                expect(page.locator('#orders-body details')).to_have_attribute('open','')
                for query in ['keep destination', '人工备注']:
                    page.locator('#search').fill(query)
                    expect(page.locator('#orders-body tr')).to_have_count(1)
                    expect(page.locator('#orders-body')).to_contain_text('DEMO-SAME')
                page.locator('#search').fill('')
                # Selections survive filters, and select-all applies only to visible rows.
                page.get_by_role('checkbox', name='选择订单 DEMO-SAME', exact=True).check()
                page.locator('#search').fill('DEMO-UPDATED')
                page.get_by_role('checkbox', name='全选当前筛选订单', exact=True).check()
                expect(page.locator('#selection-count')).to_have_text('已选 2 票')
                page.locator('#search').fill('')
                assert page.locator('#select-visible').evaluate('(el)=>el.indeterminate')
                page.locator('#clear-selection').click()
                expect(page.locator('#selected-sync-button')).to_be_disabled()
                # Direct single-number sync does not touch other orders.
                page.locator('#single-number').fill('DEMO-SAME')
                page.locator('#single-sync-button').click()
                expect(page.locator('#task-title')).to_contain_text('同步数据 · 已完成')
                assert submissions[-1]['order_nos'] == ['DEMO-SAME']
                expect(page.locator('#orders-body')).to_contain_text('目的港为空或缺失，保留表格原值')
                saved_same = next(row for row in wps.orders if row['order_no'] == 'DEMO-SAME')
                assert saved_same['pod'] == '\u00a0KEEP DESTINATION'
                assert saved_same['remark'] == '人工备注'
                assert saved_same['pol'] == 'QINGDAO, CHINA (CN)'
                assert console.snapshot()['changes'] == []
                expect(page.locator('#orders-body tr')).to_have_count(3)
                # Selected sync includes a successful and a failing query.
                page.get_by_role('checkbox', name='选择订单 DEMO-SAME', exact=True).check()
                page.get_by_role('checkbox', name='选择订单 DEMO-FAILED', exact=True).check()
                page.locator('#selected-sync-button').click()
                expect(page.locator('#task-count')).to_contain_text('2 / 2')
                expect(page.locator('#task-title')).to_contain_text('部分失败')
                assert set(submissions[-1]['order_nos']) == {'DEMO-SAME', 'DEMO-FAILED'}
                expect(page.locator('#orders-body tr')).to_have_count(3)
                page.locator('#sync-button').click()
                expect(page.locator('#sync-button')).to_be_disabled()
                expect(page.locator('#task-count')).to_contain_text('3 / 3', timeout=15000)
                expect(page.locator('#task-title')).to_contain_text('部分失败', timeout=15000)
                assert page.locator('#stat-updated').inner_text() == '1'
                assert page.locator('#stat-unchanged').inner_text() == '1'
                assert page.locator('#stat-failed').inner_text() == '1'
                highlighted = page.locator('#orders-body tr.etd-updated')
                expect(highlighted).to_have_count(1)
                expect(highlighted).to_contain_text('DEMO-UPDATED')
                expect(highlighted).to_contain_text('已完成')
                expect(highlighted.locator('td').nth(6)).to_contain_text('官网查询 2026-10-26')
                expect(highlighted.locator('td').nth(6)).to_contain_text('同步前 2026-10-25')
                expect(highlighted.locator('td').nth(3)).to_have_text('NHAVA SHEVA')
                expect(highlighted.locator('td').first).to_have_css('background-color', 'rgb(255, 243, 176)')
                highlighted.hover()
                expect(highlighted.locator('td').first).to_have_css('background-color', 'rgb(255, 230, 128)')
                page.locator('#search').hover()
                page.locator('[data-filter=updated]').click()
                assert page.locator('#orders-body tr').count() == 1
                assert '2026-10-26' in page.locator('#orders-body').inner_text()
                page.locator('[data-filter=failed]').click()
                assert '请稍后重试' in page.locator('#orders-body').inner_text()
                page.locator('[data-filter=all]').click()
                page.locator('#search').fill('NO-MATCH')
                assert page.locator('#empty').is_visible()
                page.locator('#search').fill('')
                # Capture the default compact view after exercising expanded notes.
                page.locator('#orders-body details[open] summary').click()
                page.evaluate('window.scrollTo(0,0)')
                page.get_by_role('region',name='订单表格，可横向滚动',exact=True).evaluate('(el)=>el.scrollLeft=0')
                page.screenshot(path=str(captures / 'desktop.png'), full_page=True, animations='disabled')
                page.locator('[data-page=history]').click()
                expect(page.locator('#changes-body tr')).to_have_count(1)
                expect(page.locator('#changes-body tr.etd-updated')).to_have_count(1)
                expect(page.locator('#changes-body')).to_contain_text('NHAVA SHEVA')
                page.locator('#changes-body summary').click()
                expect(page.locator('#changes-body .remark-content')).to_have_text(HISTORY_NOTE)
                expect(page.locator('#changes-body img')).to_have_count(0)
                assert not page.evaluate('window.badNote || false')
                page.screenshot(path=str(captures / 'history.png'), full_page=True, animations='disabled')
                expect(page.locator('#changes-body')).to_contain_text('2026-10-25')
                assert page.locator('#history-list').count() == 0
                expect(page.locator('#page-history')).not_to_contain_text('同步任务记录')
                page.locator('[data-page=logs]').click()
                expect(page.locator('#terminal-logs')).to_contain_text('已写入 WPS 并验证')
                page.screenshot(path=str(captures / 'logs.png'), full_page=True, animations='disabled')
                page.locator('[data-page=realtime]').click()
                page.get_by_role('button', name='同步订单 DEMO-SAME', exact=True).click()
                expect(page.locator('#task-title')).to_contain_text('同步数据 · 已完成')
                assert submissions[-1]['order_nos'] == ['DEMO-SAME']
                expect(page.locator('#orders-body tr')).to_have_count(3)
                # Refresh live notes while retaining the saved history snapshot.
                wps.orders[0]['remark']='更新后的人工备注'
                page.locator('#read-button').click()
                expect(page.locator('#task-title')).to_contain_text('读取订单 · 已完成')
                expect(page.locator('#orders-body')).to_contain_text('更新后的人工备注')
                page.locator('[data-page=history]').click()
                expect(page.locator('#changes-body .remark-content')).to_have_text(HISTORY_NOTE)
                expect(page.locator('#changes-body')).not_to_contain_text('更新后的人工备注')
                page.locator('[data-page=realtime]').click()
                page.set_viewport_size({'width':390,'height':844})
                page.evaluate('window.scrollTo(0,0)')
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                scroll=page.get_by_role('region',name='订单表格，可横向滚动',exact=True)
                assert scroll.evaluate('(el)=>el.scrollWidth>el.clientWidth')
                scroll.evaluate('(el)=>el.scrollLeft=el.scrollWidth')
                action=page.get_by_role('button',name='同步订单 DEMO-SAME',exact=True)
                box=action.bounding_box()
                assert box and box['x']>=0 and box['x']+box['width']<=390
                expect(action).to_be_enabled()
                page.screenshot(path=str(captures / 'mobile.png'), full_page=True, animations='disabled')
                # Pending writes display confirmed values as primary, query values as annotations.
                pending = dict(order_no='PENDING', original_etd='2026-10-21', latest_etd='2026-10-25',
                    queried_etd='2026-10-31', before_etd='2026-10-25', status='failed', failure_stage='write',
                    pol='CONFIRMED LOADING', pod='\u00a0CONFIRMED DISCHARGE', queried_pol='UNCONFIRMED PORT',
                    queried_pod='CONFIRMED DISCHARGE',
                    message='写入待确认', remark=None)
                old_change = dict(order_no='OLD-HISTORY', original_etd='2026-10-21', before_etd=None,
                    queried_etd='2026-10-26', valid_to='2026-10-25', changed_at='2026-10-27T12:00:00+08:00')
                page.route('**/api/state', lambda route: route.fulfill(content_type='application/json',
                    body=json.dumps(dict(configured=True, orders=[pending], jobs=[], changes=[old_change]))))
                page.reload()
                expect(page.locator('#orders-body tr')).to_have_count(1)
                latest = page.locator('#orders-body td').nth(6)
                assert latest.evaluate('(el)=>el.firstChild.textContent') == '2026-10-25'
                expect(latest).to_contain_text('官网查询 2026-10-31')
                port = page.locator('#orders-body td').nth(2)
                expect(port.locator('.port-name')).to_have_text('CONFIRMED LOADING')
                expect(port).to_contain_text('官网查得 UNCONFIRMED PORT')
                expect(page.locator('#orders-body td').nth(3)).not_to_contain_text('官网查得')
                expect(page.locator('#orders-body .remark-cell')).to_have_text('—')
                page.locator('[data-page=history]').click()
                expect(page.locator('#changes-body tr')).to_have_count(1)
                expect(page.locator('#changes-body .port-name')).to_have_text(['—', '—'])
                expect(page.locator('#changes-body .remark-cell')).to_have_text('—')
                assert not errors, errors
                browser.close()
                print('Browser UI checks passed: read, sync, progress, statistics, filters, errors, search, history, mobile.')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

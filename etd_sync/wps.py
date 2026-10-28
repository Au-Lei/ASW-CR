import json
import re
from urllib.parse import urlparse

import requests


class WpsClient:
    def __init__(self, url, token, sheet):
        parsed = urlparse(url)
        if (parsed.scheme != 'https' or parsed.hostname not in
                {'www.kdocs.cn', 'kdocs.cn', 'www.wps.cn', 'www.wps.com'}
                or not parsed.path.endswith('/sync_task') or '/api/v3/ide/file/' not in parsed.path):
            raise ValueError('请配置 WPS AirScript 同步 webhook（以 /sync_task 结尾），不能使用分享链接')
        if not token or not sheet:
            raise ValueError('请配置 WPS_API_TOKEN 和 WPS_SHEET_NAME')
        self.url, self.token, self.sheet = url, token, sheet

    def call(self, action, **kwargs):
        try:
            response = requests.post(self.url, headers={'AirScript-Token': self.token},
                                     json={'Context': {'argv': {'action': action, 'sheet': self.sheet, **kwargs}}},
                                     timeout=60, allow_redirects=False)
        except requests.RequestException:
            raise RuntimeError('WPS 网络请求失败；若为写入超时，请重新读取确认结果后再运行') from None
        if response.status_code != 200:
            raise RuntimeError(f'WPS HTTP 状态异常：{response.status_code}')
        try:
            body = response.json()
            if body.get('error') or body.get('status') != 'finished':
                detail = str(body.get('error') or body.get('message') or
                             f"状态={body.get('status', '未知')}")
                detail = detail.replace(self.token, '[TOKEN]').replace(self.url, '[WEBHOOK]')
                detail = re.sub(r'https?://\S+', '[URL]', detail)[:500]
                if "undefined (reading 'Cells')" in detail:
                    detail += f'；未找到配置的工作表“{self.sheet}”，请核对 .env 中 WPS_SHEET_NAME 与表格底部名称'
                if '表头不匹配：A1=' in detail:
                    detail += '；线上 AirScript 仍是固定列旧版，请将本地 wps/etd_bridge.js 完整替换并保存，再重新读取；无需把新表改回旧列顺序'
                raise RuntimeError(f'WPS 脚本执行失败：{detail}')
            result = body['data']['result']
            if isinstance(result, str):
                result = json.loads(result)
            if not isinstance(result, dict) or result.get('ok') is not True:
                message = result.get('message', '结果格式不正确') if isinstance(result, dict) else '结果格式不正确'
                raise RuntimeError(f'WPS：{message}')
            return result
        except (ValueError, KeyError, TypeError):
            raise RuntimeError('WPS 返回格式不正确，请确认已安装配套 AirScript') from None

    def read(self):
        result = self.call('read')
        orders = result.get('orders')
        if not isinstance(orders, list):
            raise RuntimeError('WPS 订单结果格式异常')
        if any(not isinstance(o, dict) or not {'order_no', 'original_etd', 'latest_etd',
                'valid_to', 'current_status'}.issubset(o) for o in orders):
            raise RuntimeError('WPS 脚本版本过旧，请将最新版 wps/etd_bridge.js 完整替换到 AirScript 并保存，需返回 Valid to 和当前状态')
        if any(('pol' in o) != ('pod' in o) for o in orders):
            raise RuntimeError('WPS 港口字段不完整，请更新配套脚本并检查港口表头')
        return orders

    def _write(self, action, order, *, latest=None, current_status=None, ports=None):
        payload = dict(order_no=order['order_no'], expected_original=order['original_etd'],
                       expected_latest=order['latest_etd'])
        expected = {}
        if latest is not None:
            payload['latest_etd'] = expected['latest_etd'] = latest.isoformat()
        if current_status is not None:
            payload.update(current_status=current_status, expected_valid_to=order.get('valid_to'),
                           expected_status=order.get('current_status'))
            expected['current_status'] = current_status
        ports = {} if ports is None else ports
        if not isinstance(ports, dict) or set(ports) - {'pol', 'pod'}:
            raise ValueError('仅允许更新起运港、目的港')
        for key, value in ports.items():
            if (key not in order or not isinstance(value, str) or not value.strip() or
                    len(value) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in value) or
                    value.strip()[0] in '=+@-'):
                raise ValueError('港口字段或名称无效')
            payload[key] = expected[key] = value.strip()
            payload['expected_' + key] = order[key]
        if action == 'update_ports' and not ports:
            raise ValueError('缺少待更新港口')
        result = self.call(action, **payload)
        if ports and (result.get('schema_version') != 2 or result.get('order_no') != order['order_no']):
            raise RuntimeError('港口写入未确认，请更新配套 WPS 脚本并重新读取确认')
        labels = {'latest_etd': '最新 ETD', 'current_status': '当前状态', 'pol': '起运港', 'pod': '目的港'}
        for key, value in expected.items():
            if result.get(key) != value:
                raise RuntimeError(labels[key] + '写入未确认，请更新 WPS 脚本后重新读取确认')
        return result

    def update(self, order, latest, current_status=None, *, ports=None):
        return self._write('update', order, latest=latest, current_status=current_status, ports=ports)

    def update_status(self, order, current_status, *, ports=None):
        return self._write('update_status', order, current_status=current_status, ports=ports)

    def update_ports(self, order, ports, current_status=None):
        return self._write('update_ports', order, ports=ports, current_status=current_status)

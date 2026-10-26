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
        return self.call('read')['orders']

    def update(self, order, latest):
        return self.call('update', order_no=order['order_no'],
                         expected_original=order['original_etd'],
                         expected_latest=order['latest_etd'], latest_etd=latest.isoformat())

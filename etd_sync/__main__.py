import argparse
import json
import logging
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from .dates import needs_update, parse_date
from .evergreen import EvergreenClient
from .orders import port_changes
from .wps import WpsClient

ROOT = Path(__file__).resolve().parent.parent


def run(orders, fetch, update, *, dry_run, year, interval, limit=None, update_ports=None):
    counts = Counter(str(o['order_no']).strip() for o in orders)
    failures = 0
    for index, order in enumerate(orders[:limit] if limit else orders):
        number = str(order['order_no']).strip()
        try:
            if counts[number] != 1:
                raise ValueError('表格内单号重复，跳过')
            original = parse_date(order['original_etd'], year)
            saved = parse_date(order['latest_etd'], year)
            if original is None:
                raise ValueError('原始 ETD 为空，跳过')
            if index:
                time.sleep(interval)
            result = fetch(number)
            latest = result['etd']
            if latest is None:
                raise ValueError('官网没有返回有效 ETD')
            ports, warnings = port_changes(order, result)
            for warning in warnings:
                logging.warning('%s %s', number, warning)
            if needs_update(original, saved, latest):
                if dry_run:
                    logging.info('%s 原始=%s 最新=%s：待更新（预览）', number, original, latest)
                else:
                    update(order, latest, **({'ports': ports} if ports else {}))
                    logging.info('%s 已写回并验证：%s', number, latest)
            elif ports:
                if dry_run:
                    logging.info('%s 港口待更新（预览）：%s', number, ports)
                else:
                    if update_ports is None:
                        raise ValueError('调用方未提供港口写回接口')
                    update_ports(order, ports)
                    logging.info('%s ETD 无需变更，港口已写回并验证', number)
            else:
                logging.info('%s 最新=%s：无需更新', number, latest)
        except Exception as exc:
            failures += 1
            # Browser errors may contain sensitive tracking page data; only show our own errors.
            detail = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
            logging.error('%s 失败：%s；保留原值', number, detail)
    return failures


def main():
    parser = argparse.ArgumentParser(description='长荣 ETD → WPS；默认只预览，--apply 才写入')
    parser.add_argument('--apply', action='store_true', help='实际更新共享表格')
    parser.add_argument('--demo', action='store_true', help='使用本地样例，不连接外网')
    parser.add_argument('--read-only', action='store_true', help='只读取 WPS，不查询长荣')
    parser.add_argument('--limit', type=int, help='本次最多查询多少票')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit 必须大于 0')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    (ROOT / 'logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(
                            ROOT / 'logs' / f'{datetime.now():%Y-%m-%d}.log', encoding='utf-8')])
    try:
        year = int(os.environ['DATE_YEAR']) if os.getenv('DATE_YEAR') else None
        interval = float(os.getenv('QUERY_INTERVAL_SECONDS', '3'))
        if interval < 0:
            raise ValueError('查询间隔不能为负数')
        update_ports = None
        if args.demo:
            fixture = json.loads((ROOT / 'examples' / 'demo.json').read_text(encoding='utf-8'))
            orders = fixture['orders']
            fetch = lambda number: {'etd': parse_date(fixture['results'][number])}
            update = lambda order, latest: None
        else:
            client = WpsClient(os.getenv('WPS_WEBHOOK_URL', ''), os.getenv('WPS_API_TOKEN', ''),
                               os.getenv('WPS_SHEET_NAME', '工作表1'))
            orders = client.read()
            fetch = EvergreenClient(os.getenv('HEADLESS', 'true').lower() == 'true',
                                    os.getenv('EVERGREEN_NUMBER_TYPE', 'booking')).fetch
            update = client.update
            update_ports = client.update_ports
        logging.info('读取 %s 票订单；模式：%s', len(orders), '本地演示' if args.demo else
                     ('实际写入' if args.apply else '预览'))
        if args.read_only:
            for order in orders:
                logging.info('%s', order)
            return 0
        return 1 if run(orders, fetch, update, dry_run=not args.apply or args.demo,
                        year=year, interval=interval, limit=args.limit, update_ports=update_ports) else 0
    except Exception as exc:
        logging.error('%s', str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

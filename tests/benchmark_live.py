"""Explicit, read-only live comparison. Does not call WPS update.

Run from project root: python tests/benchmark_live.py --limit 3
The baseline uses a fresh browser per order and 3s spacing; the optimized path
uses a single browser and two isolated lanes with 1s global start spacing.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from etd_sync.batch import query_batch
from etd_sync.evergreen import EvergreenClient
from etd_sync.wps import WpsClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.limit <= 5:
        parser.error('limit must be 1–5')
    load_dotenv(ROOT / '.env')
    wps = WpsClient(os.environ['WPS_WEBHOOK_URL'], os.environ['WPS_API_TOKEN'], os.environ['WPS_SHEET_NAME'])
    numbers = list(dict.fromkeys(str(order['order_no']).strip() for order in wps.read()))[:args.limit]
    if not numbers:
        raise SystemExit('No orders to compare.')
    client = EvergreenClient(number_type=os.getenv('EVERGREEN_NUMBER_TYPE', 'booking'))
    results = {}
    started = time.perf_counter()
    baseline = {}
    for index, number in enumerate(numbers):
        if index:
            time.sleep(3)
        try:
            baseline[number] = client.fetch(number)['etd'].isoformat()
        except Exception as exc:
            baseline[number] = {'error': type(exc).__name__}
        print(f'Baseline {index+1}/{len(numbers)}', flush=True)
    results['baseline_seconds'] = round(time.perf_counter() - started, 2)

    async def optimized():
        found = {}
        async with client.session(min(2,len(numbers))) as session:
            async def collect(index, result, error, seconds):
                found[numbers[index]] = {'error':type(error).__name__} if error else result['etd'].isoformat()
                print(f'Optimized {len(found)}/{len(numbers)}', flush=True)
            await query_batch(list(enumerate(numbers)),session.fetch,lambda index: None,collect,
                              concurrency=2,interval=1)
        return found
    started = time.perf_counter()
    new = asyncio.run(optimized())
    results.update(optimized_seconds=round(time.perf_counter()-started,2), sample_size=len(numbers),
                   all_succeeded=all(isinstance(v,str) for v in [*baseline.values(),*new.values()]),
                   results_match=baseline==new)
    (ROOT/'logs').mkdir(exist_ok=True)
    (ROOT/'logs'/'performance_check.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()

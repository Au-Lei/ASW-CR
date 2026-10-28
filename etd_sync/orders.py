"""Pure order reconciliation, target selection and history projection rules."""

from .dates import parse_date

SOURCE_FIELDS = ('original_etd', 'latest_etd', 'valid_to', 'current_status')
QUERY_FIELDS = ('before_etd', 'queried_etd', 'failure_stage', 'queried_pol', 'queried_pod',
                'pol_raw', 'pod_raw', 'warnings', 'ports_updated', 'ports_written_at')


def normalize_targets(mode, order_nos):
    if order_nos is None:
        return None
    if (mode != 'sync' or not isinstance(order_nos, list) or not 1 <= len(order_nos) <= 5000 or
            any(not isinstance(n, str) or not n.strip() or len(n.strip()) > 200 for n in order_nos)):
        raise ValueError('请选择至少一票有效订单，最多 5000 票；单号须为不超过 200 字的文本')
    return list(dict.fromkeys(n.strip() for n in order_nos))


def reconcile_orders(raw, previous):
    """Refresh WPS values while retaining query results only for matching rows."""
    if not isinstance(raw, list):
        raise ValueError('WPS 订单结果格式异常')
    previous = {str(order['order_no']): order for order in previous}
    orders = []
    for order in raw:
        number = str(order['order_no']).strip()
        old = previous.get(number, {})
        changed = bool(old) and (any(old.get(key) != order.get(key) for key in SOURCE_FIELDS) or
                                 any(key in order and old.get(key) != order[key] for key in ('pol', 'pod')))
        orders.append({**order, 'order_no': number, 'last_checked': old.get('last_checked'),
                       'status': 'unqueried' if changed else old.get('status', 'unqueried'),
                       'message': '表格数据已变化，请重新同步' if changed else old.get('message', ''),
                       'pol': order.get('pol', old.get('pol', '')),
                       'ports_enabled': 'pol' in order and 'pod' in order,
                       **{key: None if changed else old.get(key) for key in QUERY_FIELDS}})
    return orders


def port_changes(order, result):
    """Only write confirmed nonempty ports to rows with real WPS port columns."""
    if not order.get('ports_enabled', 'pol' in order and 'pod' in order):
        return {}, []
    changes, warnings = {}, []
    for key, label in (('pol', '起运港'), ('pod', '目的港')):
        value = result.get(key)
        if value is None or isinstance(value, str) and not value.strip():
            warnings.append(f'官网{label}为空或缺失，保留表格原值')
            continue
        if (not isinstance(value, str) or len(value) > 200 or
                any(ord(c) < 32 or ord(c) == 127 for c in value) or value.strip()[0] in '=+@-'):
            raise ValueError(f'官网{label}格式异常，未写回')
        value = value.strip()
        if value != str(order.get(key) or '').strip():
            changes[key] = value
    return changes, warnings


def target_indices(orders, targets):
    numbers = None if targets is None else set(targets)
    if numbers is not None and numbers - {order['order_no'] for order in orders}:
        raise ValueError('选中的单号已不在 WPS 中，请重新读取订单后再选择；本次未查询或写入')
    # Keep duplicate rows: the sync preflight must reject them, never pick one.
    return [i for i, order in enumerate(orders) if numbers is None or order['order_no'] in numbers]


def history_changes(jobs):
    """Project only verified ETD changes beyond their original Valid to snapshot."""
    changes = []
    for job in jobs:
        if job.get('mode') != 'sync':
            continue
        for item in job['items']:
            if item['status'] != 'updated':
                continue
            try:
                valid_to = parse_date(item.get('valid_to'), job.get('date_year'))
                latest = parse_date(item.get('queried_etd'))
            except (ValueError, TypeError, OverflowError):
                continue
            if valid_to is not None and latest is not None and latest > valid_to:
                changes.append({**item, 'job_id': job['id'], 'valid_to': valid_to.isoformat(),
                                'changed_at': item.get('written_at') or item.get('processed_at') or
                                job.get('finished_at') or job['created_at']})
    return sorted(changes, key=lambda item: item['changed_at'], reverse=True)

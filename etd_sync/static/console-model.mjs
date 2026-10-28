// Pure display models: safe to test in Node without a browser.
export const jobLabels = {
  running: '正在处理', completed: '已完成', partial: '部分失败',
  failed: '执行失败', interrupted: '已中断',
};

export function formatDate(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number' && value > 10000) {
    return new Date(Date.UTC(1899, 11, 30) + Math.floor(value) * 86400000).toISOString().slice(0, 10);
  }
  return String(value);
}

export function formatTime(value) {
  return value ? value.slice(0, 19).replace('T', ' ') : '—';
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '';
  if (seconds < 60) return seconds.toFixed(1) + ' 秒';
  return Math.floor(seconds / 60) + ' 分 ' + Math.round(seconds % 60) + ' 秒';
}

export function countItems(job, status) {
  return job ? job.items.filter(item => item.status === status).length : 0;
}

export function orderRows(state) {
  const lastSync = state.jobs.find(job => job.mode === 'sync');
  const active = state.jobs.find(job => job.status === 'running');
  const items = new Map((lastSync?.items || []).map(item => [String(item.order_no), item]));
  let rows = state.orders.map(order => {
    const item = items.get(String(order.order_no));
    const expected = item?.status === 'updated' ? item.queried_etd : item?.latest_etd;
    const matches = item && !['unqueried', 'interrupted'].includes(order.status) &&
      JSON.stringify(item.original_etd) === JSON.stringify(order.original_etd) &&
      JSON.stringify(expected) === JSON.stringify(order.latest_etd);
    return {
      ...order,
      failure_stage: matches ? item.failure_stage : order.failure_stage,
      before_etd: matches ? item.before_etd : order.before_etd,
      queried_etd: matches ? item.queried_etd : order.queried_etd,
    };
  });
  if (active?.mode === 'sync') {
    const activeItems = new Map(active.items.map(item => [String(item.order_no), item]));
    rows = rows.map(order => {
      const item = activeItems.get(String(order.order_no));
      return item ? {...item, latest_etd: confirmedEtd(item)} : order;
    });
  }
  return rows;
}

// Only a verified ETD update can promote the query value to the table value.
export function confirmedEtd(item) {
  return item.status === 'updated' && item.queried_etd ? item.queried_etd : item.latest_etd;
}

export function numberCounts(orders) {
  const counts = new Map();
  for (const order of orders) {
    const number = String(order.order_no);
    counts.set(number, (counts.get(number) || 0) + 1);
  }
  return counts;
}

export function filterOrders(orders, filter, query) {
  query = query.trim().toLowerCase();
  return orders.filter(item => {
    const matchesStatus = filter === 'all' || (filter === 'failed'
      ? ['failed', 'interrupted'].includes(item.status) : item.status === filter);
    return matchesStatus && ['order_no', 'pol', 'pod', 'remark'].some(key =>
      String(item[key] ?? '').toLowerCase().includes(query));
  });
}

export function runtimeLogs(jobs) {
  const logs = [];
  for (const job of [...jobs].reverse()) {
    logs.push({
      at: job.created_at, level: 'INFO', message: job.mode === 'sync'
        ? '接收到手动同步指令，开始读取 WPS 订单。' : '接收到读取订单指令。',
    });
    for (const item of job.items) {
      if (item.status === 'waiting') continue;
      const level = ['updated', 'unchanged'].includes(item.status) ? (item.warnings?.length ? 'WARN' : 'SUCCESS')
        : ['failed', 'interrupted'].includes(item.status) ? 'ERROR' : 'INFO';
      logs.push({
        at: item.processed_at || item.attempted_at || job.created_at,
        level,
        message: item.order_no + ' · ' + item.message +
          (item.queried_etd ? ' · 官网 ETD ' + item.queried_etd : ''),
      });
    }
    if (job.status !== 'running') {
      logs.push({
        at: job.finished_at,
        level: ['failed', 'interrupted'].includes(job.status) ? 'ERROR'
          : job.status === 'partial' ? 'WARN' : 'SUCCESS',
        message: job.message,
      });
    }
  }
  return logs;
}

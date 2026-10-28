import assert from 'node:assert/strict';
import test from 'node:test';
import {orderRows, filterOrders, numberCounts, runtimeLogs,
  formatDate, formatTime, formatDuration, confirmedEtd} from '../etd_sync/static/console-model.mjs';

test('selected sync retains the other orders and their previous query results', () => {
  const other = {order_no: 'OTHER', original_etd: '2026-10-21', latest_etd: null,
    queried_etd: '2026-10-21', status: 'unchanged'};
  const chosen = {order_no: 'SELECTED', original_etd: '2026-10-21',
    latest_etd: '2026-10-26', status: 'updated'};
  const state = {orders: [other, chosen], jobs: [{mode: 'sync', status: 'completed',
    items: [{...chosen, queried_etd: '2026-10-26', before_etd: null}]}]};
  const rows = orderRows(state);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].queried_etd, '2026-10-21');
  assert.equal(rows[1].queried_etd, '2026-10-26');
  assert.equal(state.orders[1].queried_etd, undefined);
});

test('active selected sync overlays only its own rows', () => {
  const state = {orders: [{order_no: 'A'}, {order_no: 'B'}], jobs: [
    {mode: 'sync', status: 'running', items: [{order_no: 'B', status: 'querying'}]}]};
  const rows = orderRows(state);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].status, undefined);
  assert.equal(rows[1].status, 'querying');
});

test('external edits never reuse an old successful query', () => {
  const state = {orders: [{order_no: 'A', original_etd: '2026-10-20',
    latest_etd: null, status: 'unqueried'}], jobs: [{mode: 'sync', status: 'completed',
    items: [{order_no: 'A', original_etd: '2026-10-21', latest_etd: null,
      queried_etd: '2026-10-26', status: 'updated'}]}]};
  assert.equal(orderRows(state)[0].queried_etd, undefined);
});

test('filters are case insensitive, include interruptions, and preserve the source', () => {
  const rows = Object.freeze([{order_no: 'AbC', status: 'failed'},
    {order_no: 'B', status: 'interrupted'}, {order_no: 'C', status: 'updated'}]);
  assert.deepEqual(filterOrders(rows, 'failed', ' abc '), [rows[0]]);
  assert.deepEqual(filterOrders(rows, 'failed', ''), [rows[0], rows[1]]);
  assert.deepEqual(filterOrders(rows, 'updated', ''), [rows[2]]);
  assert.equal(rows.length, 3);
});

test('duplicate counts prevent treating repeated order numbers as a single target', () => {
  const counts = numberCounts([{order_no: 'A'}, {order_no: 'A'}, {order_no: 'B'}]);
  assert.equal(counts.get('A'), 2);
  assert.equal(counts.get('B'), 1);
});

test('failure logs use this attempt timestamp, never a stale success timestamp', () => {
  const jobs = [{mode: 'sync', status: 'partial', created_at: 'start', finished_at: 'finish',
    message: '部分失败', items: [{order_no: 'A', status: 'failed', message: '超时',
      processed_at: 'this-attempt', last_checked: 'old-success'}]}];
  const logs = runtimeLogs(jobs);
  assert.equal(logs[1].at, 'this-attempt');
  assert.equal(logs[1].level, 'ERROR');
  assert.equal(logs[2].level, 'WARN');
  assert.equal(jobs[0].items[0].last_checked, 'old-success');
});

test('display formats preserve Excel dates and Beijing time strings', () => {
  assert.equal(formatDate(46321), '2026-10-26');
  assert.equal(formatDate(null), '—');
  assert.equal(formatTime('2026-10-27T12:00:00+08:00'), '2026-10-27 12:00:00');
  assert.equal(formatDuration(65), '1 分 5 秒');
});


test('missing-port warnings remain visible in runtime logs without becoming ETD updates', () => {
  const job = {mode: 'sync', status: 'completed', created_at: '2026-10-28', items: [{
    order_no: 'PORT', status: 'unchanged', ports_updated: ['pol'], warnings: ['目的港缺失'],
    message: '港口已写回；目的港缺失，保留表格原值',
  }]};
  const entry = runtimeLogs([job]).find(log => log.message.startsWith('PORT'));
  assert.equal(entry.level, 'WARN');
  assert.match(entry.message, /保留表格原值/);
  assert.equal(job.items[0].status, 'unchanged');
});


test('search covers both ports and the full remark, including old rows with missing fields', () => {
  const rows = [{order_no: 'PORT', pol: 'Qingdao', pod: 'Nhava Sheva', remark: '首行\n尾部关键词', status: 'unchanged'},
    {order_no: 'LEGACY', status: 'updated'}, {order_no: 'ZERO', remark: 0, status: 'unqueried'}];
  for(const query of [' qINGdao ', 'SHEVA', '尾部关键词']) assert.deepEqual(filterOrders(rows,'all',query), [rows[0]]);
  assert.deepEqual(filterOrders(rows,'updated','sheva'), []);
  assert.deepEqual(filterOrders(rows,'all','0'), [rows[2]]);
  assert.deepEqual(filterOrders(rows,'all',''), rows);
  assert.deepEqual(filterOrders(rows,'all','undefined'), []);
});

test('only confirmed writes promote queried dates, including active job rows', () => {
  const base={order_no:'A', latest_etd:'2026-10-25', queried_etd:'2026-10-31'};
  assert.equal(confirmedEtd({...base,status:'failed',failure_stage:'write'}),'2026-10-25');
  assert.equal(confirmedEtd({...base,status:'querying'}),'2026-10-25');
  assert.equal(confirmedEtd({...base,status:'updated'}),'2026-10-31');
  assert.equal(confirmedEtd({latest_etd:null,status:'unchanged',queried_etd:'2026-10-21'}),null);
  const state={orders:[{...base,status:'waiting'}],jobs:[{mode:'sync',status:'running',items:[{...base,status:'updated'}]}]};
  assert.equal(orderRows(state)[0].latest_etd,'2026-10-31');
  state.jobs[0].items[0].status='failed';
  assert.equal(orderRows(state)[0].latest_etd,'2026-10-25');
});

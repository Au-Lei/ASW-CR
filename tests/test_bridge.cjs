const fs = require('node:fs');
const assert = require('node:assert/strict');
const code = fs.readFileSync('wps/etd_bridge.js', 'utf8');
function execute(rows, argv, styles = new Map(), options = {}) {
  const sheet = {
    UsedRange: {Row: 1, Rows: {Count: rows.length}, Column: 1,
      Columns: {Count: Math.max(...rows.map(row => row.length))}},
    Range(address) {
      assert.match(address, /^A\d+:D\d+$/);
      return {Interior: {set Color(color) {
        if (options.failHighlight) throw new Error('背景设置失败');
        styles.set(address, color);
      }}};
    },
    Cells(row, col) {
      return {
        get Value2() { return rows[row - 1][col - 1]; },
        set Value2(value) {
          if (!options.failWrite && !(options.failStatusWrite && col === 6)) rows[row - 1][col - 1] = value;
        },
        set NumberFormat(value) {}
      };
    }
  };
  return new Function('Application', 'Context', 'RGB', code)(
    {Worksheets: {Item: () => sheet}}, {argv: {sheet: '工作表1', ...argv}},
    (r, g, b) => r + 256 * g + 65536 * b);
}
const header = ['提单号', 'ETD（原BC）', 'Valid to', 'ETD', '当前状态'];
const original = '2026-10-21';
const rows = [header, ['OTHER', original, null, null], ['TEST', original, null, null]];
const withValidity = [header, ['TEST', original, '2026-10-25', null]];
assert.equal(execute(withValidity, {action: 'read'}).orders[0].valid_to, '2026-10-25');
assert.equal(execute(rows, {action: 'read'}).orders.length, 2);
assert.equal(execute([['提单号', 'ETD（原BC）', 'Valid to', '最新ETD', '当前状态'],
  ['TEST', original, null, null]], {action: 'read'}).orders.length, 1);
const args = {action: 'update', order_no: 'TEST', expected_original: original,
  expected_latest: null, latest_etd: '2026-10-26'};
const styles = new Map([['A2:D2', 123]]);
assert.equal(execute(rows, args, styles).row, 3);
assert.equal(styles.get('A3:D3'), 255 + 243 * 256 + 176 * 65536);
assert.equal(styles.get('A2:D2'), 123);
assert.equal(styles.size, 2);
assert.equal(rows[2][3], '2026-10-26');
assert.equal(rows[1][3], null);
assert.equal(rows[2][1], original);
execute(withValidity, args);
assert.equal(withValidity[1][2], '2026-10-25');
assert.throws(() => execute(rows, args), /修改/);
assert.throws(() => execute([header, ['TEST', original, null, null], ['TEST', original, null, null]], args), /重复/);
assert.throws(() => execute([header, ['TEST', original, null, null]], {...args, latest_etd: '2026-02-30'}), /有效/);
assert.throws(() => execute([['WRONG', ...header.slice(1)]], {action: 'read'}), /表头/);
assert.throws(() => execute([[header[0], header[1], '其他日期', header[3]]], {action: 'read'}), /C1=Valid to/);
// Read-only, stale values, invalid dates and failed writes never add highlights.
const untouched = new Map();
execute(rows, {action: 'read'}, untouched);
assert.throws(() => execute(rows, args, untouched), /修改/);
assert.throws(() => execute([header, ['TEST', original, null, null]],
  {...args, latest_etd: '2026-02-30'}, untouched), /有效/);
assert.throws(() => execute([header, ['TEST', original, null, null]],
  args, untouched, {failWrite: true}), /写入后校验失败/);
execute(rows, {...args, expected_latest: '2026-10-26'}, untouched);
assert.equal(untouched.size, 0);
// A formatting failure must not be reported as a successful update.
assert.throws(() => execute([header, ['TEST', original, null, null]],
  args, untouched, {failHighlight: true}), /背景设置失败/);
// Locate status by its header even when a notes column comes before it.
const statusHeader = [...header.slice(0, 4), '备注', '当前状态'];
const statusRows = [statusHeader, ['TEST', original, '2026-10-25', '2026-10-26', '保留备注', 'ETD已变更']];
const statusArgs = {action: 'update_status', order_no: 'TEST', expected_original: original,
  expected_latest: '2026-10-26', expected_valid_to: '2026-10-25',
  expected_status: 'ETD已变更', current_status: '已完成'};
assert.equal(execute(statusRows, {action: 'read'}).orders[0].current_status, 'ETD已变更');
assert.throws(() => execute(statusRows, {...statusArgs, expected_valid_to: '2026-10-24'}), /已被修改/);
assert.throws(() => execute(statusRows, {...statusArgs, expected_status: 'ETD未变更'}), /已被修改/);
assert.throws(() => execute(statusRows, {...statusArgs, current_status: '随便填'}), /状态无效/);
assert.throws(() => execute(statusRows, statusArgs, untouched, {failStatusWrite: true}), /当前状态写入后校验失败/);
assert.equal(execute(statusRows, statusArgs, untouched).current_status, '已完成');
assert.deepEqual(statusRows[1].slice(0, 5), ['TEST', original, '2026-10-25', '2026-10-26', '保留备注']);
assert.equal(untouched.size, 0);
const changedRows = [statusHeader, ['TEST', original, '2026-10-25', null, '保留备注', null]];
assert.equal(execute(changedRows, {...args, expected_valid_to: '2026-10-25', expected_status: null,
  current_status: '托班到下一批次'}).current_status, '托班到下一批次');
assert.equal(changedRows[1][5], '托班到下一批次');
assert.throws(() => execute([[...header, '当前状态']], {action: 'read'}), /唯一/);
assert.throws(() => execute([header.slice(0, 4)], {action: 'read'}), /当前状态/);
console.log('AirScript mock integration tests passed.');

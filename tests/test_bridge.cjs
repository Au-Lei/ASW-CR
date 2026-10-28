const fs = require('node:fs');
const assert = require('node:assert/strict');
const code = fs.readFileSync('wps/etd_bridge.js', 'utf8');
function execute(rows, argv, styles = new Map(), options = {}) {
  const sheet = {
    UsedRange: {Row: 1, Rows: {Count: rows.length}, Column: 1,
      Columns: {Count: Math.max(...rows.map(row => row.length))}},
    Range(address) {
      assert.match(address, /^[A-Z]+\d+:[A-Z]+\d+$/);
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
assert.equal(styles.get('A3:E3'), 255 + 243 * 256 + 176 * 65536);
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
assert.throws(() => execute([[header[0], header[1], '其他日期', header[3]]], {action: 'read'}), /Valid to/);
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
// New layout: ports are read from the sheet, remarks and manual dates are protected.
const newHeader = ['提单号', '起运港', '目的港', 'ETD（原BC）', 'Valid to', 'ETD', '当前状态', '备注'];
function newRows() { return [newHeader.slice(), ['TEST', 'SHANGHAI', null, original, '2026-10-25', null, null, '船公司甩货，不影响价格']]; }
const newData = newRows();
const read = execute(newData, {action: 'read'});
assert.equal(read.schema_version, 2);
assert.equal(read.columns.latest_etd, 6);
assert.equal(read.orders[0].pol, 'SHANGHAI');
assert.equal(read.orders[0].pod, null);
assert.equal(read.orders[0].remark, '船公司甩货，不影响价格');
const ports = {pol: 'QINGDAO', expected_pol: 'SHANGHAI', pod: 'NHAVA SHEVA', expected_pod: null};
const newArgs = {...args, ...ports, expected_valid_to: '2026-10-25', expected_status: null, current_status: '托班到下一批次'};
const newStyles = new Map();
execute(newData, newArgs, newStyles);
assert.deepEqual(newData[1], ['TEST', 'QINGDAO', 'NHAVA SHEVA', original, '2026-10-25', '2026-10-26', '托班到下一批次', '船公司甩货，不影响价格']);
assert.equal(newStyles.get('A2:H2'), 255 + 243 * 256 + 176 * 65536);
// Port-only updates must work without touching ETD, notes, or background.
const portData = newRows();
execute(portData, {...args, action: 'update_ports', ...ports}, untouched);
assert.equal(portData[1][5], null);
assert.equal(portData[1][7], '船公司甩货，不影响价格');
assert.equal(untouched.size, 0);
// Validate all fields before the first write, including concurrent manual edits.
for (const invalid of [{expected_pol: 'OLD'}, {expected_pod: 'OLD'}, {pod: ''}, {pod: '=FORMULA()'}, {pod: null}]) {
  const data = newRows(), before = JSON.stringify(data);
  assert.throws(() => execute(data, {...newArgs, ...invalid}), /修改|港口名称/);
  assert.equal(JSON.stringify(data), before);
}
const missingExpected = {...newArgs}; delete missingExpected.expected_pod;
assert.throws(() => execute(newRows(), missingExpected), /修改/);
for (const headers of [[...newHeader, ' 最新 ETD '], [...newHeader, '备注'], [...newHeader, '起运港'],
                       [...newHeader, '订舱号'], newHeader.filter(x => x !== '目的港')]) {
  assert.throws(() => execute([headers], {action: 'read'}), /唯一|成对/);
}
// Arbitrary column order and a moved row must still target the matching order.
const shuffledHeader = ['备注', '当前状态', '目的港', 'Valid to', '最新 ETD', '订舱号', 'ETD (原始)', '起运港'];
const shuffled = [shuffledHeader, ['其他备注', null, null, null, null, 'OTHER', original, null],
  ['人工新增备注', null, null, '2026-10-25', null, 'TEST', original, 'SHANGHAI']];
const shuffledResult = execute(shuffled, {...newArgs, row: 2});
assert.equal(shuffledResult.row, 3);
assert.equal(shuffled[2][0], '人工新增备注');
assert.equal(shuffled[2][4], '2026-10-26');
assert.equal(shuffled[2][6], original);
assert.equal(shuffled[1][4], null);
// Missing/ambiguous headers are rejected before mutation, never treated as positional.
const badHeaders = [newHeader.map(x => x === 'ETD（原BC）' ? '原日期' : x), [...newHeader, '最新ETD']];
for (const headers of badHeaders) {
  const data = [headers, newRows()[1]], before = JSON.stringify(data);
  assert.throws(() => execute(data, newArgs), /表头/);
  assert.equal(JSON.stringify(data), before);
}
console.log('AirScript mock integration tests passed.');

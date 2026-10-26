const fs = require('node:fs');
const assert = require('node:assert/strict');
const code = fs.readFileSync('wps/etd_bridge.js', 'utf8');
function execute(rows, argv) {
  const sheet = {
    UsedRange: {Row: 1, Rows: {Count: rows.length}},
    Cells(row, col) {
      return {
        get Value2() { return rows[row - 1][col - 1]; },
        set Value2(value) { rows[row - 1][col - 1] = value; },
        set NumberFormat(value) {}
      };
    }
  };
  return new Function('Application', 'Context', code)(
    {Worksheets: {Item: () => sheet}}, {argv: {sheet: '工作表1', ...argv}});
}
const header = ['提单号', 'ETD（原BC）', 'Valid to', 'ETD'];
const original = '2026-10-21';
const rows = [header, ['OTHER', original, null, null], ['TEST', original, null, null]];
assert.equal(execute(rows, {action: 'read'}).orders.length, 2);
assert.equal(execute([['提单号', 'ETD（原BC）', 'Valid to', '最新ETD'],
  ['TEST', original, null, null]], {action: 'read'}).orders.length, 1);
const args = {action: 'update', order_no: 'TEST', expected_original: original,
  expected_latest: null, latest_etd: '2026-10-26'};
assert.equal(execute(rows, args).row, 3);
assert.equal(rows[2][3], '2026-10-26');
assert.equal(rows[1][3], null);
assert.equal(rows[2][1], original);
assert.throws(() => execute(rows, args), /修改/);
assert.throws(() => execute([header, ['TEST', original, null, null], ['TEST', original, null, null]], args), /重复/);
assert.throws(() => execute([header, ['TEST', original, null, null]], {...args, latest_etd: '2026-02-30'}), /有效/);
assert.throws(() => execute([['WRONG', ...header.slice(1)]], {action: 'read'}), /表头/);
console.log('AirScript mock integration tests passed.');

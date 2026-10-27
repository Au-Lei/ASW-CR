// Paste the entire file into the WPS ordinary spreadsheet AirScript editor.
// This file is not for a multidimensional table. Run via synchronous webhook.
function main() {
  const args = Context.argv || {};
  if (!args.sheet) throw new Error('缺少工作表名称');
  const sheet = Application.Worksheets.Item(args.sheet);
  if (!sheet) {
    const names = [];
    for (let i = 1; i <= Application.Worksheets.Count; i++) {
      const item = Application.Worksheets.Item(i);
      if (item) names.push(item.Name);
    }
    throw new Error('未找到工作表“' + args.sheet + '”；可用工作表：' + names.join('、') +
      '。请修改本地 .env 的 WPS_SHEET_NAME，不能填写文档标题。');
  }
  const value = (row, col) => {
    const v = sheet.Cells(row, col).Value2;
    return v === undefined || v === '' ? null : v;
  };
  const text = v => v === null ? '' : String(v).trim();
  const headers = [1, 2, 3, 4].map(col => text(value(1, col)));
  const normalized = headers[1].replace(/\s/g, '').replace(/（/g, '(').replace(/）/g, ')');
  if (!['提单号', '订舱号', '单号'].includes(headers[0]) ||
      !['ETD(原BC)', 'ETD(原始)'].includes(normalized) ||
      headers[2].replace(/\s/g, '').toLowerCase() !== 'validto' ||
      !['ETD', '最新ETD'].includes(headers[3].replace(/\s/g, ''))) {
    throw new Error('表头不匹配：A1=提单号或订舱号，B1=ETD（原BC），C1=Valid to，D1=ETD或最新ETD');
  }
  const used = sheet.UsedRange;
  const statusColumns = [];
  const lastColumn = used.Column + used.Columns.Count - 1;
  for (let col = 1; col <= lastColumn; col++) {
    if (text(value(1, col)).replace(/\s/g, '') === '当前状态') statusColumns.push(col);
  }
  if (statusColumns.length !== 1 || statusColumns[0] <= 4) {
    throw new Error('请在 D 列之后添加唯一的“当前状态”列，不能覆盖 A–D 业务列');
  }
  const statusColumn = statusColumns[0];
  const lastRow = used.Row + used.Rows.Count - 1;
  if (lastRow > 5000) throw new Error('使用范围超过5000行，请清理多余格式或调整脚本上限');
  const orders = [];
  for (let row = 2; row <= lastRow; row++) {
    const number = text(value(row, 1));
    if (number) orders.push({order_no: number, original_etd: value(row, 2), valid_to: value(row, 3),
      latest_etd: value(row, 4), current_status: value(row, statusColumn), row});
  }
  if (args.action === 'read') return {ok: true, orders};
  if (!['update', 'update_status'].includes(args.action)) throw new Error('未知操作');
  const matches = orders.filter(order => order.order_no === text(args.order_no));
  if (matches.length !== 1) throw new Error('单号不存在或重复，拒绝写入');
  const order = matches[0];
  // Compare raw values as an optimistic concurrency check, including column D.
  if (JSON.stringify(order.original_etd) !== JSON.stringify(args.expected_original) ||
      JSON.stringify(order.latest_etd) !== JSON.stringify(args.expected_latest)) {
    throw new Error('查询期间该行已被修改，请重新读取');
  }
  const hasStatus = Object.prototype.hasOwnProperty.call(args, 'current_status');
  if (args.action === 'update_status' && !hasStatus) throw new Error('缺少当前状态');
  if (hasStatus) {
    if (!['ETD未变更', 'ETD已变更', '托班到下一批次', '已完成'].includes(args.current_status)) {
      throw new Error('当前状态无效');
    }
    if (JSON.stringify(order.valid_to) !== JSON.stringify(args.expected_valid_to) ||
        JSON.stringify(order.current_status) !== JSON.stringify(args.expected_status)) {
      throw new Error('查询期间 Valid to 或当前状态已被修改，请重新读取');
    }
  }
  function writeStatus() {
    if (!hasStatus) return;
    sheet.Cells(order.row, statusColumn).Value2 = args.current_status;
    if (text(value(order.row, statusColumn)) !== args.current_status) {
      throw new Error('当前状态写入后校验失败，请重新读取确认');
    }
  }
  if (args.action === 'update_status') {
    writeStatus();
    return {ok: true, order_no: order.order_no, row: order.row, current_status: args.current_status};
  }
  const latest = args.latest_etd;
  if (typeof latest !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(latest) ||
      isNaN(Date.parse(latest)) || new Date(latest).toISOString().slice(0, 10) !== latest) {
    throw new Error('最新ETD必须是有效的YYYY-MM-DD日期');
  }
  const cell = sheet.Cells(order.row, 4);
  // Store a complete unambiguous date string, avoiding regional auto conversion.
  cell.NumberFormat = '@';
  cell.Value2 = latest;
  if (text(value(order.row, 4)) !== latest) throw new Error('写入后校验失败，请重新读取确认');
  // Highlight only the business columns, after the changed ETD is verified.
  // Existing highlights are retained; reads and unchanged orders do not recolor cells.
  if (text(order.latest_etd) !== latest) {
    sheet.Range('A' + order.row + ':D' + order.row).Interior.Color = RGB(255, 243, 176);
  }
  writeStatus();
  return {ok: true, order_no: order.order_no, row: order.row, latest_etd: latest,
    current_status: hasStatus ? args.current_status : order.current_status};
}
return main();

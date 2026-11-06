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
  const text = v => v === null || v === undefined ? '' : String(v).trim();
  // Resolve business fields by unique normalized headers, never by column position.
  const normalize = v => text(v).replace(/\s/g, '').replace(/（/g, '(').replace(/）/g, ')').toLowerCase();
  const aliases = {
    order_no: ['提单号', '订舱号', '单号'], pol: ['起运港'], pod: ['目的港'],
    original_etd: ['etd(原bc)', 'etd(原始)'], valid_to: ['validto'],
    latest_etd: ['etd', '最新etd'], current_status: ['当前状态'], remark: ['备注'], booking_status: ['status', 'bookingstatus']
  };
  const labels = {order_no: '提单号/订舱号', pol: '起运港', pod: '目的港',
    original_etd: 'ETD（原BC）', valid_to: 'Valid to', latest_etd: 'ETD/最新ETD',
    current_status: '当前状态', remark: '备注', booking_status: 'Status'};
  const used = sheet.UsedRange;
  const lastColumn = used.Column + used.Columns.Count - 1;
  if (lastColumn > 256) throw new Error('使用范围超过256列，请清理多余格式');
  const columns = {};
  for (let col = 1; col <= lastColumn; col++) {
    const header = normalize(value(1, col));
    for (const key of Object.keys(aliases)) {
      if (!aliases[key].includes(header)) continue;
      if (columns[key]) throw new Error('表头“' + labels[key] + '”必须唯一，存在重复或别名冲突');
      columns[key] = col;
    }
  }
  for (const key of ['order_no', 'original_etd', 'valid_to', 'latest_etd', 'current_status']) {
    if (!columns[key]) throw new Error('缺少表头“' + labels[key] + '”，请核对第一行');
  }
  if (Boolean(columns.pol) !== Boolean(columns.pod)) {
    throw new Error('起运港、目的港表头必须成对出现，缺少“' + (columns.pol ? '目的港' : '起运港') + '”');
  }
  const statusColumn = columns.current_status;
  const lastRow = used.Row + used.Rows.Count - 1;
  if (lastRow > 5000) throw new Error('使用范围超过5000行，请清理多余格式或调整脚本上限');
  const orders = [];
  for (let row = 2; row <= lastRow; row++) {
    const number = text(value(row, columns.order_no));
    if (!number) continue;
    const order = {order_no: number, row};
    for (const key of Object.keys(columns)) {
      if (key !== 'order_no') order[key] = value(row, columns[key]);
    }
    orders.push(order);
  }
  if (args.action === 'read') return {ok: true, schema_version: 2, columns, orders};
  if (!['update', 'update_status', 'update_ports', 'update_booking_status', 'archive'].includes(args.action)) throw new Error('未知操作');
  const matches = orders.filter(order => order.order_no === text(args.order_no));
  if (matches.length !== 1) throw new Error('单号不存在或重复，拒绝写入');
  const order = matches[0];
  // Resolve the row afresh on every call; compare raw snapshots before any write.
  if (JSON.stringify(order.original_etd) !== JSON.stringify(args.expected_original) ||
      JSON.stringify(order.latest_etd) !== JSON.stringify(args.expected_latest)) {
    throw new Error('查询期间该行已被修改，请重新读取');
  }
  if (args.action === 'archive') {
    if (args.sheet === '已完成') throw new Error('不能从已完成表再次归档');
    const reasons = {'Loading': '货物已装船', 'Loaded': '货物已装船',
      'Cut Off': '已截关/截港', 'Cancelled': '订舱已取消', 'Cancel': '订舱已取消'};
    const normalizeStatus = v => text(v).toLowerCase().replace(/\s+/g, ' ');
    const reasonKey = Object.keys(reasons).find(key => normalizeStatus(key) === normalizeStatus(order.booking_status));
    const reason = reasons[reasonKey];
    if (!reason || !columns.booking_status || !columns.remark) throw new Error('Status 不符合归档条件或缺少备注列');
    for (const key of Object.keys(columns)) {
      if (key !== 'order_no' && JSON.stringify(order[key]) !== JSON.stringify((args.expected_row || {})[key])) {
        throw new Error('归档期间该行已被修改，请重新读取');
      }
    }
    const target = Application.Worksheets.Item('已完成');
    if (!target) throw new Error('请先创建已完成工作表并复制原表全部表头');
    const width = lastColumn;
    const targetColumns = target.UsedRange.Column + target.UsedRange.Columns.Count - 1;
    if (targetColumns > 256) throw new Error('已完成表使用范围超过256列，请清理多余格式');
    const targetHeaders = {};
    for (let col = 1; col <= targetColumns; col++) {
      const header = normalize(target.Cells(1, col).Value2);
      if (!header) continue;
      if (targetHeaders[header]) throw new Error('已完成表存在重复表头，未删除原行');
      targetHeaders[header] = col;
    }
    let appendColumn = Math.max(0, ...Object.values(targetHeaders));
    const mapping = [];
    const seen = new Set();
    for (let col = 1; col <= width; col++) {
      const header = normalize(value(1, col));
      if (!header) {
        if (value(order.row, col) !== null) throw new Error('来源行存在无表头数据，未删除原行');
        continue;
      }
      if (seen.has(header)) throw new Error('来源表存在重复表头，未删除原行');
      seen.add(header);
      let destinationColumn = targetHeaders[header];
      if (!destinationColumn) {
        destinationColumn = ++appendColumn;
        if (destinationColumn > 256) throw new Error('已完成表列数超过上限');
        target.Cells(1, destinationColumn).Value2 = value(1, col);
        targetHeaders[header] = destinationColumn;
      }
      mapping.push([col, destinationColumn]);
    }
    const targetOrderColumn = mapping.find(pair => pair[0] === columns.order_no)[1];
    const rowValues = [];
    for (let col = 1; col <= width; col++) rowValues.push(value(order.row, col));
    rowValues[columns.current_status - 1] = '已完成';
    rowValues[columns.remark - 1] = reason;
    const targetLast = target.UsedRange.Row + target.UsedRange.Rows.Count - 1;
    if (targetLast > 5000) throw new Error('已完成表超过5000行，未删除原行');
    let destination = 0;
    for (let row = 2; row <= targetLast; row++) {
      if (text(target.Cells(row, targetOrderColumn).Value2) !== order.order_no) continue;
      if (destination) throw new Error('已完成表存在重复单号，未删除原行');
      destination = row;
      for (const [col, targetCol] of mapping) {
        const v = target.Cells(row, targetCol).Value2;
        if (JSON.stringify(v === undefined || v === '' ? null : v) !== JSON.stringify(rowValues[col - 1])) {
          throw new Error('已完成表已有同单号但数据不同，未删除原行');
        }
      }
    }
    if (!destination) {
      destination = Math.max(2, targetLast + 1);
      for (const [col, targetCol] of mapping) {
        const cell = target.Cells(destination, targetCol);
        cell.NumberFormat = sheet.Cells(order.row, col).NumberFormat;
        if (typeof rowValues[col - 1] === 'string') cell.NumberFormat = '@';
        cell.Value2 = rowValues[col - 1];
      }
    }
    for (const [col, targetCol] of mapping) {
      const v = target.Cells(destination, targetCol).Value2;
      if (JSON.stringify(v === undefined || v === '' ? null : v) !== JSON.stringify(rowValues[col - 1])) {
        throw new Error('已完成表写入校验失败，未删除原行');
      }
    }
    sheet.Rows(order.row).Delete();
    return {ok: true, order_no: order.order_no, archived: true, current_status: '已完成', remark: reason};
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
  const has = key => Object.prototype.hasOwnProperty.call(args, key);
  const portWrites = [];
  for (const key of ['pol', 'pod', 'booking_status']) {
    if (!has(key)) continue;
    if (!columns[key]) throw new Error('请先添加起运港、目的港表头');
    const port = args[key];
    if (typeof port !== 'string' || !port.trim() || port.length > 200 ||
        /[\x00-\x1f\x7f]/.test(port) || /^[=+@-]/.test(port.trim())) {
      throw new Error(labels[key] + '必须是有效的非空港口名称');
    }
    if (!has('expected_' + key) || JSON.stringify(order[key]) !== JSON.stringify(args['expected_' + key])) {
      throw new Error('查询期间' + labels[key] + '已被修改，请重新读取');
    }
    portWrites.push([key, port.trim()]);
  }
  if (args.action === 'update_booking_status' && !has('booking_status')) throw new Error('缺少 Booking Status');
  if (args.action === 'update_ports' && !portWrites.length) throw new Error('缺少待更新港口');
  function writeText(key, content) {
    if (text(order[key]) === content) return;
    const cell = sheet.Cells(order.row, columns[key]);
    cell.NumberFormat = '@';
    cell.Value2 = content;
    if (text(value(order.row, columns[key])) !== content) {
      throw new Error(labels[key] + '写入后校验失败，请重新读取确认');
    }
  }
  function writeDetails() {
    for (const [key, port] of portWrites) writeText(key, port);
    if (hasStatus) {
      writeText('current_status', args.current_status);
      const colors = {'ETD未变更': [230, 244, 234], 'ETD已变更': [255, 243, 176],
        '托班到下一批次': [253, 226, 226], '已完成': [255, 255, 255]};
      const indexes = Object.values(columns);
      const letter = index => {
        let name = '';
        while (index > 0) { index--; name = String.fromCharCode(65 + index % 26) + name; index = Math.floor(index / 26); }
        return name;
      };
      sheet.Range(letter(Math.min(...indexes)) + order.row + ':' +
        letter(Math.max(...indexes)) + order.row).Interior.Color = RGB(...colors[args.current_status]);
    }
  }
  function result() {
    const data = {ok: true, order_no: order.order_no, row: order.row, schema_version: 2};
    for (const key of ['latest_etd', 'current_status', 'pol', 'pod', 'remark', 'booking_status']) {
      if (columns[key]) data[key] = value(order.row, columns[key]);
    }
    return data;
  }
  if (args.action !== 'update') {
    writeDetails();
    return result();
  }
  const latest = args.latest_etd;
  if (typeof latest !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(latest) ||
      isNaN(Date.parse(latest)) || new Date(latest).toISOString().slice(0, 10) !== latest) {
    throw new Error('最新ETD必须是有效的YYYY-MM-DD日期');
  }
  writeText('latest_etd', latest);
  // Only ETD changes highlight the recognized business range, retaining old colors.
  if (text(order.latest_etd) !== latest) {
    const indexes = Object.values(columns);
    const letter = index => {
      let name = '';
      while (index > 0) { index--; name = String.fromCharCode(65 + index % 26) + name; index = Math.floor(index / 26); }
      return name;
    };
    sheet.Range(letter(Math.min(...indexes)) + order.row + ':' +
      letter(Math.max(...indexes)) + order.row).Interior.Color = RGB(255, 243, 176);
  }
  writeDetails();
  return result();
}
return main();

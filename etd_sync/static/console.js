import {jobLabels, formatDate as date, formatTime as time, formatDuration as duration,
  countItems as count, numberCounts as countNumbers, orderRows, filterOrders,
  runtimeLogs, confirmedEtd} from './console-model.mjs';
const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let state = {orders: [], jobs: []}, filter = 'all', pending = false, timer;
const selectedNumbers = new Set();
const expandedNotes = new Set();
let visibleSelectable = [];
const pageTitles = {realtime:'实时数据变更',history:'历史变更记录',logs:'系统运行记录',help:'使用说明'};
function switchPage(page) {
  document.querySelectorAll('.page-section').forEach(section=>section.hidden=section.id!=='page-'+page);
  document.querySelectorAll('.menu-item').forEach(button=>{
    button.classList.toggle('active',button.dataset.page===page);
    if(button.dataset.page===page) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  });
  $('page-title').textContent=pageTitles[page];
}
const labels = {updated:'已更新', unchanged:'无需变更', failed:'失败', querying:'查询中', waiting:'待查询', unqueried:'未查询', interrupted:'已中断'};

const text = (tag, value, className) => { const el = document.createElement(tag); el.textContent = value; if(className) el.className = className; return el; };
const displayText = value => value === null || value === undefined || value === '' ? '—' : String(value);
function portCell(item, key, showQuery = false) {
  const cell = text('td', '', 'port-cell');
  cell.append(text('span', displayText(item[key]), 'port-name'));
  const queried = item['queried_' + key];
  if(showQuery && queried && String(queried).trim() !== String(item[key] ?? '').trim()) cell.append(text('span', '官网查得 '+queried, 'subline'));
  return cell;
}
function remarkCell(item, key) {
  const cell = text('td', '', 'remark-cell');
  const value = displayText(item.remark);
  if(value.length <= 100 && value.split('\n').length <= 3) {
    cell.append(text('div', value, 'remark-content'));
    return cell;
  }
  const details=document.createElement('details');
  details.open=expandedNotes.has(key);
  const summary=text('summary', value.replace(/\s+/g,' ').slice(0,60)+'… · 展开/收起');
  summary.dataset.focusKey='remark:'+key;
  summary.setAttribute('aria-label', '展开或收起 '+item.order_no+' 的完整备注');
  details.append(summary,text('div',value,'remark-content'));
  summary.addEventListener('click',event=>{
    // Save immediately: a search or polling render can precede the async toggle event.
    event.preventDefault();
    details.open=!details.open;
    if(details.open) expandedNotes.add(key); else expandedNotes.delete(key);
  });
  cell.append(details);
  return cell;
}

function badge(status) { return text('span',labels[status] || status,'badge '+status); }
function showError(message) { $('error').textContent=message; $('error').hidden=!message; }
function render() {
  const focusedKey=document.activeElement?.dataset.focusKey;
  const active=state.jobs.find(job=>job.status==='running');
  const numberCounts=countNumbers(state.orders);
  for(const n of selectedNumbers) if(numberCounts.get(n)!==1) selectedNumbers.delete(n);
  const context={latest:state.jobs[0],active,busy:!!active || pending,
    lastSync:state.jobs.find(job=>job.mode==='sync'),numberCounts};
  renderSummary(context);
  renderOrders(context);
  renderHistory();
  renderLogs();
  if(focusedKey) [...document.querySelectorAll('[data-focus-key]')].find(el=>el.dataset.focusKey===focusedKey)?.focus({preventScroll:true});
}

function renderSummary({latest,active,busy,lastSync}) {
  const stats=lastSync;
  $('connection').className='connection '+(state.configured?'ready':'offline');
  $('connection').replaceChildren(text('span','','dot'),document.createTextNode(state.configured?'WPS 已配置':'WPS 待配置'));
  $('sheet-name').textContent = state.sheet || 'WPS 共享表格';
  $('stat-total').textContent = state.orders.length;
  $('stat-updated').textContent = stats ? count(stats,'updated') : '—';
  $('stat-unchanged').textContent = stats ? count(stats,'unchanged') : '—';
  $('stat-failed').textContent = stats ? count(stats,'failed') : '—';
  $('stat-failed').style.color = count(stats,'failed') ? 'var(--red)' : '';
  for(const id of ['read-button','sync-button','single-number','single-sync-button']) $(id).disabled=busy;
  $('sync-button').querySelector('span').textContent=active?.mode==='sync'?'正在同步…':'手动同步数据';
  $('read-button').textContent=active?.mode==='read'?'正在读取…':'读取订单';
  $('task-title').textContent = latest ? (latest.mode==='read'?'读取订单':'同步数据')+' · '+jobLabels[latest.status] : '准备就绪';
  $('task-message').textContent = latest?.message || '首次使用，请读取订单或直接同步数据。';
  $('task-mark').className='status-mark '+(active?'running':['failed','partial','interrupted'].includes(latest?.status)?'failed':'');
  $('task-count').textContent=latest?.mode==='sync' && latest.total ? latest.processed+' / '+latest.total+' 票'+(latest.duration_seconds!==undefined?' · 用时 '+duration(latest.duration_seconds):'') : '';
  $('progress').hidden=!active;
  $('progress').value=latest?.total ? latest.processed/latest.total*100 : 0;
  $('last-sync').textContent = lastSync ? '最近同步：'+time(lastSync.finished_at || lastSync.created_at)+'（北京时间）' : '尚未执行同步';
  $('header-sync-time').textContent=lastSync?time(lastSync.finished_at || lastSync.created_at):'尚未执行';
}

function renderOrders({busy,lastSync,numberCounts}) {
  const source=orderRows(state);
  $('orders-title').textContent='订单列表';
  $('table-note').textContent=lastSync?.scope==='selected'?'最近一次仅同步 '+lastSync.total+' 票；其余订单保留各自最近查询结果':'表格数据以最近一次读取为准';
  for(const type of ['all','updated','failed']) $('count-'+type).textContent=type==='all'?source.length:source.filter(item=>type==='failed'?['failed','interrupted'].includes(item.status):item.status===type).length;
  const visible=filterOrders(source,filter,$('search').value);
  visibleSelectable=visible.map(item=>String(item.order_no)).filter(n=>numberCounts.get(n)===1);
  $('selection-count').textContent='已选 '+selectedNumbers.size+' 票';
  $('selected-sync-button').disabled=busy || !selectedNumbers.size;
  $('clear-selection').disabled=busy || !selectedNumbers.size;
  const checkedVisible=visibleSelectable.filter(n=>selectedNumbers.has(n)).length;
  $('select-visible').checked=visibleSelectable.length>0 && checkedVisible===visibleSelectable.length;
  $('select-visible').indeterminate=checkedVisible>0 && checkedVisible<visibleSelectable.length;
  $('select-visible').disabled=busy || !visibleSelectable.length;
  $('result-count').textContent='显示 '+visible.length+' 票';
  document.querySelectorAll('.filter').forEach(button=>{const chosen=button.dataset.filter===filter;button.classList.toggle('active',chosen);button.setAttribute('aria-pressed',chosen);});
  $('orders-body').replaceChildren(...visible.map(item=>{
    const row=document.createElement('tr');
    if(item.status==='updated') row.classList.add('etd-updated');
    const n=String(item.order_no), duplicate=numberCounts.get(n)!==1;
    const choice=document.createElement('input');choice.type='checkbox';choice.checked=selectedNumbers.has(n);
    choice.disabled=busy || duplicate;choice.setAttribute('aria-label','选择订单 '+n);choice.dataset.focusKey='select:'+n;
    choice.addEventListener('change',()=>{if(choice.checked) selectedNumbers.add(n);else selectedNumbers.delete(n);render();});
    const choiceCell=text('td','','selection-cell');choiceCell.append(choice);row.append(choiceCell);
    row.append(text('td',item.order_no,'order-number'),portCell(item,'pol',true),portCell(item,'pod',true),
      text('td',date(item.original_etd),'date'),text('td',date(item.valid_to),'date'));
    const latest=text('td',date(confirmedEtd(item)),item.status==='updated'?'date new-date':'date');
    if(item.queried_etd) {
      latest.append(text('span','官网查询 '+date(item.queried_etd),'subline'),
        text('span','同步前 '+date(item.before_etd),'subline'));
    }
    row.append(latest,text('td',item.current_status || '—'),remarkCell(item,JSON.stringify(['orders',n])));
    const result=document.createElement('td');const tag=badge(item.status);
    if(item.failure_stage==='write') tag.textContent='写入待确认';
    result.append(tag);if(['failed','interrupted'].includes(item.status) || item.status==='unqueried' && item.message || item.ports_updated?.length || item.warnings?.length) result.append(text('span',item.message,'subline'));row.append(result,text('td',time(item.last_checked),'small'));
    const action=text('button','单票同步','text-button');action.type='button';action.disabled=busy || duplicate;
    action.setAttribute('aria-label','同步订单 '+n);action.dataset.focusKey='sync:'+n;
    if(duplicate) action.title='单号重复，请先在 WPS 核对';
    action.addEventListener('click',()=>start('sync',[n]));const actionCell=text('td','','row-action');actionCell.append(action);row.append(actionCell);return row;
  }));
  $('empty').hidden=visible.length>0;
  $('empty-title').textContent=source.length?'没有符合条件的订单':'暂无订单数据';
  if(source.length) $('empty-message').textContent='可以切换筛选条件，或搜索单号、港口和备注。';
  else if(state.jobs.length) $('empty-message').textContent='共享表格暂未读取到订单。请检查单号列，再点击“读取订单”。';
}

function renderHistory() {
  const changes=state.changes || [];
  $('changes-body').replaceChildren(...changes.map(item=>{
    const row=document.createElement('tr');
    row.classList.add('etd-updated');
    row.append(text('td',time(item.changed_at)),text('td',item.order_no),portCell(item,'pol'),portCell(item,'pod'),
      text('td',date(item.original_etd)),text('td',date(item.before_etd)),
      text('td',date(item.valid_to)),text('td',date(item.queried_etd),'new-date'),
      remarkCell(item,JSON.stringify(['history',item.job_id,item.order_no,item.changed_at])));
    const status=document.createElement('td');status.append(badge('updated'));row.append(status);return row;
  }));
  $('changes-empty').hidden=changes.length>0;
}

function renderLogs() {
  const logs=runtimeLogs(state.jobs);
  $('log-count').textContent=logs.length+' 条记录';
  $('terminal-logs').replaceChildren(...logs.map(log=>{
    const row=text('div','','log-row');row.append(text('span','['+time(log.at)+']','log-time'),
      text('span','['+log.level+']','log-level '+(log.level==='SUCCESS'?'log-success':log.level==='ERROR'?'log-error':log.level==='WARN'?'log-warn':'')),
      text('span',log.message,'log-message'));return row;
  }));
  if(!logs.length) $('terminal-logs').append(text('p','等待执行首次任务…'));
}

async function refresh() {
  clearTimeout(timer);
  try {const response=await fetch('/api/state');if(!response.ok) throw new Error('无法读取服务状态，请刷新页面重试。');state=await response.json();render();}
  catch(error){$('connection').className='connection offline';$('connection').replaceChildren(text('span','','dot'),document.createTextNode('连接中断'));showError(error.message || '连接中断，请检查服务是否运行。');}
  timer=setTimeout(refresh,state.jobs.some(job=>job.status==='running')?1000:5000);
}
async function start(mode, orderNos) {
  if(pending || state.jobs.some(job=>job.status==='running')) return;
  if(orderNos!==undefined && (!orderNos.length || orderNos.some(n=>!n.trim()))){showError('请选择订单或输入完整单号');return;}
  pending=true;filter='all';showError('');render();
  try {
    const payload={mode};if(orderNos!==undefined) payload.order_nos=orderNos;
    const response=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)});
    const body=await response.json();if(!response.ok) throw new Error(body.error || '启动任务失败');
    if(mode==='sync'){if(orderNos) orderNos.forEach(n=>selectedNumbers.delete(n));else selectedNumbers.clear();}
  }catch(error){showError(error.message || '启动任务失败，请重试。');}
  finally{pending=false;await refresh();}
}
$('read-button').addEventListener('click',()=>start('read'));
$('sync-button').addEventListener('click',()=>start('sync'));
$('single-sync-form').addEventListener('submit',event=>{event.preventDefault();start('sync',[$('single-number').value.trim()]);});
$('selected-sync-button').addEventListener('click',()=>start('sync',[...selectedNumbers]));
$('clear-selection').addEventListener('click',()=>{selectedNumbers.clear();render();});
$('select-visible').addEventListener('change',()=>{for(const n of visibleSelectable){if($('select-visible').checked) selectedNumbers.add(n);else selectedNumbers.delete(n);}render();});
$('search').addEventListener('input',render);
document.querySelectorAll('.filter').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.filter;render();}));
document.querySelectorAll('.menu-item').forEach(button=>button.addEventListener('click',()=>switchPage(button.dataset.page)));
refresh();

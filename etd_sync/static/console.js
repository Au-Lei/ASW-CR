'use strict';
const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let state = {orders: [], jobs: []}, filter = 'all', selectedId = null, pending = false, timer;
let currentPage = 'realtime';
const pageTitles = {realtime:'实时数据变更',history:'历史变更记录',logs:'系统运行记录',help:'使用说明'};
function switchPage(page) {
  currentPage=page;
  document.querySelectorAll('.page-section').forEach(section=>section.hidden=section.id!=='page-'+page);
  document.querySelectorAll('.menu-item').forEach(button=>{
    button.classList.toggle('active',button.dataset.page===page);
    if(button.dataset.page===page) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  });
  $('page-title').textContent=pageTitles[page];
}
const labels = {updated:'已更新', unchanged:'无需变更', failed:'失败', querying:'查询中', waiting:'待查询', unqueried:'未查询', interrupted:'已中断'};
const jobLabels = {running:'正在处理', completed:'已完成', partial:'部分失败', failed:'执行失败', interrupted:'已中断'};
const text = (tag, value, className) => { const el = document.createElement(tag); el.textContent = value; if(className) el.className = className; return el; };
function date(value) { if(value === null || value === undefined || value === '') return '—'; if(typeof value === 'number' && value > 10000) return new Date(Date.UTC(1899,11,30)+Math.floor(value)*86400000).toISOString().slice(0,10); return String(value); }
function time(value) { return value ? value.slice(0,19).replace('T',' ') : '—'; }
function duration(seconds) { if(seconds === null || seconds === undefined) return ''; return seconds < 60 ? seconds.toFixed(1)+' 秒' : Math.floor(seconds/60)+' 分 '+Math.round(seconds%60)+' 秒'; }
function count(job, status) { return job ? job.items.filter(item => item.status === status).length : 0; }
function badge(status) { return text('span',labels[status] || status,'badge '+status); }
function showError(message) { $('error').textContent=message; $('error').hidden=!message; }
function render() {
  const focusedJobId=document.activeElement?.dataset.jobId;
  const latest = state.jobs[0], active = state.jobs.find(job=>job.status==='running');
  const lastSync = state.jobs.find(job=>job.mode==='sync');
  const selected = state.jobs.find(job=>job.id===selectedId);
  const stats = selected || lastSync;
  $('connection').className='connection '+(state.configured?'ready':'offline');
  $('connection').replaceChildren(text('span','','dot'),document.createTextNode(state.configured?'WPS 已配置':'WPS 待配置'));
  $('sheet-name').textContent = state.sheet || 'WPS 共享表格';
  $('stat-total').textContent = state.orders.length;
  $('stat-updated').textContent = stats ? count(stats,'updated') : '—';
  $('stat-unchanged').textContent = stats ? count(stats,'unchanged') : '—';
  $('stat-failed').textContent = stats ? count(stats,'failed') : '—';
  $('stat-failed').style.color = count(stats,'failed') ? 'var(--red)' : '';
  for(const id of ['read-button','sync-button']) $(id).disabled=!!active || pending;
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
  let source;
  if(selected) source=selected.items;
  else {
    const items = new Map((lastSync?.items || []).map(item=>[String(item.order_no),item]));
    source = state.orders.map(order=>{
      const item=items.get(String(order.order_no));
      const expected=item?.status==='updated'?item.queried_etd:item?.latest_etd;
      const matches=item && !['unqueried','interrupted'].includes(order.status) &&
        JSON.stringify(item.original_etd)===JSON.stringify(order.original_etd) &&
        JSON.stringify(expected)===JSON.stringify(order.latest_etd);
      return {...order,before_etd:matches?item.before_etd:null,queried_etd:matches?item.queried_etd:null,
        failure_stage:matches?item.failure_stage:null};
    });
    if(active?.mode==='sync') source=active.items;
  }
  $('orders-title').textContent=selected?'同步明细':'订单列表';
  $('table-note').textContent=selected?time(selected.created_at)+' · 历史记录':'表格数据以最近一次读取为准';
  $('back-button').hidden=!selected;
  for(const type of ['all','updated','failed']) $('count-'+type).textContent=type==='all'?source.length:source.filter(item=>type==='failed'?['failed','interrupted'].includes(item.status):item.status===type).length;
  const query=$('search').value.trim().toLowerCase();
  const visible=source.filter(item=>(filter==='all'||(filter==='failed'?['failed','interrupted'].includes(item.status):item.status===filter)) && String(item.order_no).toLowerCase().includes(query));
  $('result-count').textContent='显示 '+visible.length+' 票';
  document.querySelectorAll('.filter').forEach(button=>{const chosen=button.dataset.filter===filter;button.classList.toggle('active',chosen);button.setAttribute('aria-pressed',chosen);});
  $('orders-body').replaceChildren(...visible.map(item=>{
    const row=document.createElement('tr');
    const number=text('td',item.order_no);if(item.pol) number.append(text('span',item.pol,'subline'));row.append(number);
    row.append(text('td',date(item.original_etd),'date'),text('td',date(item.before_etd),'date'));
    const latest=text('td',date(item.queried_etd),item.status==='updated'?'date new-date':'date');
    if(!item.queried_etd && item.latest_etd) latest.append(text('span','表格现值 '+date(item.latest_etd),'subline'));
    row.append(latest);
    const result=document.createElement('td');const tag=badge(item.status);
    if(item.failure_stage==='write') tag.textContent='写入待确认';
    result.append(tag);if(['failed','interrupted'].includes(item.status) || item.status==='unqueried' && item.message) result.append(text('span',item.message,'subline'));row.append(result,text('td',time(item.last_checked),'small'));return row;
  }));
  $('empty').hidden=visible.length>0;
  $('empty-title').textContent=source.length?'没有符合条件的订单':selected?'本次没有订单':'暂无订单数据';
  if(source.length) $('empty-message').textContent='可以切换筛选条件，或尝试其他单号。';
  else if(state.jobs.length) $('empty-message').textContent='共享表格暂未读取到订单。请检查单号列，再点击“读取订单”。';
  $('history-list').replaceChildren(...state.jobs.map(job=>{
    const row=text('div','','history-row');row.append(text('time',time(job.created_at)),text('span',job.mode==='sync'?'船期同步':'读取订单'));
    const summary=text('div','','history-summary');
    if(job.mode==='sync') summary.textContent=jobLabels[job.status]+' · '+job.total+' 票 · 更新 '+count(job,'updated')+' · 无变化 '+count(job,'unchanged')+' · 失败 '+count(job,'failed');
    else summary.textContent=jobLabels[job.status]+' · '+job.message;
    if(job.mode==='sync' && job.concurrency) summary.textContent+=' · '+job.concurrency+' 票并发';
    if(job.duration_seconds!==undefined) summary.textContent+=' · 用时 '+duration(job.duration_seconds);
    row.append(summary);
    if(job.mode==='sync'){const button=text('button','查看明细','text-button');button.type='button';button.dataset.jobId=job.id;button.addEventListener('click',()=>{selectedId=job.id;filter='all';$('search').value='';switchPage('realtime');render();$('orders-title').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});});row.append(button);}return row;
  }));
  if(!state.jobs.length) $('history-list').append(text('p','暂无操作记录。','small'));
  const changes=state.jobs.flatMap(job=>job.items.filter(item=>item.status==='updated').map(item=>({job,item})));
  $('changes-body').replaceChildren(...changes.map(({job,item})=>{
    const row=document.createElement('tr');
    row.append(text('td',time(item.written_at || item.processed_at || job.finished_at)),text('td',item.order_no),
      text('td',date(item.original_etd)),text('td',date(item.before_etd)),
      text('td',date(item.queried_etd),'new-date'));
    const status=document.createElement('td');status.append(badge('updated'));row.append(status);return row;
  }));
  $('changes-empty').hidden=changes.length>0;
  const logs=[];
  for(const job of [...state.jobs].reverse()) {
    logs.push({at:job.created_at,level:'INFO',message:job.mode==='sync'?'接收到手动同步指令，开始读取 WPS 订单。':'接收到读取订单指令。'});
    for(const item of job.items) {
      if(['waiting'].includes(item.status)) continue;
      const level=item.status==='updated'?'SUCCESS':['failed','interrupted'].includes(item.status)?'ERROR':item.status==='unchanged'?'SUCCESS':'INFO';
      logs.push({at:item.processed_at || item.attempted_at || job.created_at,level,message:item.order_no+' · '+item.message+(item.queried_etd?' · 官网 ETD '+item.queried_etd:'')});
    }
    if(job.status!=='running') logs.push({at:job.finished_at,level:['failed','interrupted'].includes(job.status)?'ERROR':job.status==='partial'?'WARN':'SUCCESS',message:job.message});
  }
  $('log-count').textContent=logs.length+' 条记录';
  $('terminal-logs').replaceChildren(...logs.map(log=>{
    const row=text('div','','log-row');row.append(text('span','['+time(log.at)+']','log-time'),
      text('span','['+log.level+']','log-level '+(log.level==='SUCCESS'?'log-success':log.level==='ERROR'?'log-error':log.level==='WARN'?'log-warn':'')),
      text('span',log.message,'log-message'));return row;
  }));
  if(!logs.length) $('terminal-logs').append(text('p','等待执行首次任务…'));
  if(focusedJobId) [...document.querySelectorAll('#history-list button')].find(button=>button.dataset.jobId===focusedJobId)?.focus({preventScroll:true});
}
async function refresh() {
  clearTimeout(timer);
  try {const response=await fetch('/api/state');if(!response.ok) throw new Error('无法读取服务状态，请刷新页面重试。');state=await response.json();render();}
  catch(error){$('connection').className='connection offline';$('connection').replaceChildren(text('span','','dot'),document.createTextNode('连接中断'));showError(error.message || '连接中断，请检查服务是否运行。');}
  timer=setTimeout(refresh,state.jobs.some(job=>job.status==='running')?1000:5000);
}
async function start(mode) {
  if(pending || state.jobs.some(job=>job.status==='running')) return;
  pending=true;selectedId=null;filter='all';showError('');render();
  try {
    const response=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({mode})});
    const body=await response.json();if(!response.ok) throw new Error(body.error || '启动任务失败');
  }catch(error){showError(error.message || '启动任务失败，请重试。');}
  finally{pending=false;await refresh();}
}
$('read-button').addEventListener('click',()=>start('read'));
$('sync-button').addEventListener('click',()=>start('sync'));
$('search').addEventListener('input',render);
$('back-button').addEventListener('click',()=>{selectedId=null;filter='all';render();});
document.querySelectorAll('.filter').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.filter;render();}));
document.querySelectorAll('.menu-item').forEach(button=>button.addEventListener('click',()=>switchPage(button.dataset.page)));
refresh();

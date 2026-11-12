import {DAY, finite, percent, pp, dayTime, filterEtfs, mergeShards, pointsFor, segments, rangeFor, csvFor} from './model.mjs';

const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const colors = ['#3d9385','#7693b2','#ac9c7e','#8b92b7','#7faca9','#b88887','#93a779','#a598b0'];
const state = {index:null, history:mergeShards([]), country:'all', query:'', eligibleOnly:true, sort:'cagr',
  selected:null, period:'all', start:'', end:'', focusScale:false, visible:[], rowsToShow:30, loadId:0, historyError:false};
let shardCache = new Map(), chartGeometry = null;

function node(tag, attributes = {}, text = null) {
  const element = document.createElementNS(NS, tag);
  Object.entries(attributes).forEach(([key,value]) => element.setAttribute(key, String(value)));
  if (text !== null) element.textContent = text;
  return element;
}
function html(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
const rateClass = value => !finite(value) ? 'unavailable' : value < 0 ? 'negative' : 'positive';
function seriesColor(id) {return colors[[...id].reduce((sum,c) => sum + c.charCodeAt(0),0) % colors.length];}
function points(id) {return pointsFor(state.history,id,state.start,state.end,state.eligibleOnly);}
function showNotice(message, error = false) {
  $('notice').hidden = !message;
  $('notice').textContent = message;
  $('notice').classList.toggle('error',error);
}
async function getJSON(url) {
  const response = await fetch(url, {cache:'no-store'});
  if (!response.ok) throw new Error(`데이터를 불러오지 못했습니다 (HTTP ${response.status}).`);
  return response.json();
}
async function loadHistory() {
  const id = ++state.loadId;
  if (!state.index) return;
  const months = state.index.months.filter(month => month >= state.start.slice(0,7) && month <= state.end.slice(0,7));
  try {
    const shards = await Promise.all(months.map(month => {
      const key = month + ':' + state.index.updated_at;
      if (!shardCache.has(key)) {
        const promise = getJSON(`./data/history/${month}.json?v=${encodeURIComponent(state.index.updated_at)}`);
        shardCache.set(key,promise);
        promise.catch(() => shardCache.delete(key));
      }
      return shardCache.get(key);
    }));
    if (id !== state.loadId) return;
    state.history = mergeShards(shards);
    state.historyError=false;
    render();
    return true;
  } catch (error) {
    if (id === state.loadId) {
      state.historyError=true;
      showNotice(error.message + ' 저장된 원본은 GitHub에서 확인할 수 있습니다.',true);
    }
    return false;
  }
}
async function refresh(initial = false) {
  $('refresh').disabled = true;
  try {
    const index = await getJSON('./data/index.json');
    if (index.schema_version !== 1 || !Array.isArray(index.etfs) || !Array.isArray(index.dates)) throw new Error('수익률 데이터 형식을 확인해 주세요.');
    const changed = !state.index || state.historyError || state.index.updated_at !== index.updated_at || JSON.stringify(state.index.dates) !== JSON.stringify(index.dates);
    state.index = index;
    if (initial || changed) {
      shardCache = new Map();
      if (state.period !== 'custom') [state.start,state.end] = rangeFor(index.dates,state.period);
      if (initial) {
        const linked = new URLSearchParams(location.hash.slice(1)).get('etf');
        const candidates = filterEtfs(index.etfs,{latestDate:index.dates.at(-1)});
        state.selected = index.etfs.some(row => row.id === linked) ? linked : candidates[0]?.id ?? null;
      }
      renderOverview();
      if (!await loadHistory()) return;
    }
    if (!index.dates.length) showNotice('첫 수집을 기다리고 있습니다. 자동 수집이 완료되면 실제 데이터가 표시됩니다.');
    else if (dayTime(new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Seoul'})) - dayTime(index.dates.at(-1)) > 2 * DAY)
      showNotice(`마지막 저장일은 ${index.dates.at(-1)}입니다. GitHub Actions 실행 상태를 확인해 주세요.`);
    else if (index.dates.length === 1) showNotice('첫날의 실제 관측값입니다. 현재는 점 하나로 표시되며, 다음 날짜부터 기록이 쌓여 선으로 이어집니다.');
    else showNotice('');
  } catch (error) {
    showNotice(error.message + ' 잠시 후 새로고침해 주세요.',true);
    if (!state.index) {$('chart-empty').hidden=false;$('chart-empty').textContent='수익률 데이터를 아직 불러오지 못했습니다.';}
  } finally {$('refresh').disabled=false;}
}
function renderOverview() {
  const index = state.index, latest = index.dates.at(-1);
  $('etf-count').textContent = index.etfs.filter(row => row.eligible && row.last_observed_date === latest).length.toLocaleString('ko-KR');
  $('universe-count').textContent = `전체 후보 ${index.etfs.length.toLocaleString('ko-KR')}개 · 한·미 비채권 ETF`;
  $('day-count').textContent = index.dates.length.toLocaleString('ko-KR') + '일';
  $('history-span').textContent = index.dates.length ? `${index.dates[0]} — ${latest}` : '수집을 시작하면 표시됩니다.';
  $('update-time').textContent = index.updated_at ? new Date(index.updated_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) + ' KST 저장' : '첫 수집 대기 중';
  $('market-dates').textContent = `시장 기준일 · 한국 ${index.market_dates.KR ?? '—'} / 미국 ${index.market_dates.US ?? '—'}`;
  for (const id of ['start-date','end-date']) {$(id).min=index.dates[0] ?? '';$(id).max=latest ?? '';}
}
function render() {
  if (!state.index) return;
  state.visible = filterEtfs(state.index.etfs,{...state,latestDate:state.index.dates.at(-1)});
  if (state.selected && !state.visible.some(row => row.id === state.selected)) state.selected=null;
  $('start-date').value=state.start;$('end-date').value=state.end;
  document.querySelectorAll('[data-country]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.country===state.country)));
  document.querySelectorAll('[data-period]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.period===state.period)));
  renderList();renderSummary();renderChart();renderTable();
}
function renderList() {
  $('list-count').textContent=state.visible.length.toLocaleString('ko-KR');
  const fragment=document.createDocumentFragment();
  for (const row of state.visible) {
    const button=html('button','etf-row');button.type='button';button.dataset.id=row.id;
    button.setAttribute('aria-pressed',String(row.id===state.selected));
    button.setAttribute('aria-label',`${row.country} ${row.ticker} ${row.name} ${percent(row.cagr)}`);
    const line=html('span','ticker-line');line.append(html('span','ticker',row.ticker),html('span','country-tag',row.country));
    button.append(line,html('span','etf-rate '+rateClass(row.cagr),row.last_observed_date===state.index.dates.at(-1)?percent(row.cagr):'기록 종료'),html('span','etf-name',row.name));
    button.title=row.name;fragment.append(button);
  }
  if (!state.visible.length) fragment.append(html('div','empty-list','검색 결과가 없습니다.\n검색어 또는 이력 조건을 바꿔 보세요.'));
  $('etf-list').replaceChildren(fragment);
}
function select(id) {
  state.selected=id;state.rowsToShow=30;
  const hash=id?'#'+new URLSearchParams({etf:id}).toString():location.pathname+location.search;
  history.replaceState(null,'',hash);
  render();
}
function renderSummary() {
  const row=state.index.etfs.find(row=>row.id===state.selected), container=$('selected-summary');
  container.replaceChildren();
  if (!row) {
    $('chart-title').textContent='ETF 연환산수익률 추이';
    $('chart-subtitle').textContent=`${state.visible.length.toLocaleString('ko-KR')}개 ETF를 한눈에 비교합니다.`;
    container.append(html('p','summary-overview','ETF를 선택하면 수익률의 변화와 날짜별 기록이 자세히 표시됩니다.'));
    $('selection-note').textContent='차트의 선이나 ETF 목록을 클릭해 보세요.';return;
  }
  $('chart-title').textContent=`${row.ticker} · ${row.name}`;
  $('chart-subtitle').textContent=`${row.country==='US'?'미국':'한국'} · ${row.management_style} · ${row.investment_area || '투자분야 미확인'}`;
  const ps=points(row.id), valid=ps.filter(p=>finite(p.cagr)), last=ps.at(-1), change=valid.length>1?valid.at(-1).cagr-valid[0].cagr:null;
  const valueBox=html('div');
  valueBox.append(html('div','selected-value '+rateClass(last?.cagr),percent(last?.cagr)));
  valueBox.append(html('span','change-badge '+rateClass(change),finite(change)?`선택 기간 ${pp(change)}`:'다음 관측부터 변화 비교'));
  const meta=html('div','selected-meta');
  meta.append(html('strong','',last?`수집일 ${last.date}`:'선택 기간에 수집된 기록 없음'));
  meta.append(html('span','',`실제 시세 ${last?.actualDate ?? '미확인'} · 유효 관측 ${valid.length}일`));
  container.append(valueBox,meta);
  $('selection-note').textContent=last?.status==='latest_available'?'과거 가용 시세를 사용한 값입니다. 실제 시세 기준일을 확인하세요.':valid.length===1?'현재 구간에 관측값이 1개 있어 점으로 표시합니다.':'관측값이 없는 날짜는 선으로 연결하지 않습니다.';
}
function renderChart() {
  const svg=$('chart');svg.replaceChildren();chartGeometry=null;$('tooltip').hidden=true;
  const rows=state.visible.map(row=>({...row,points:points(row.id)}));
  const all=rows.flatMap(row=>row.points.filter(p=>finite(p.cagr)).map(p=>p.cagr));
  const dates=state.history.dates.filter(day=>day>=state.start&&day<=state.end);
  if (!all.length||!dates.length) {$('chart-empty').hidden=false;$('chart-empty').textContent='선택한 조건에 계산 가능한 관측값이 없습니다.';return;}
  $('chart-empty').hidden=true;
  const focused=rows.find(row=>row.id===state.selected)?.points.filter(p=>finite(p.cagr)).map(p=>p.cagr);
  const values=state.focusScale&&focused?.length?focused:all;
  let lo=Infinity,hi=-Infinity;for(const value of values){lo=Math.min(lo,value);hi=Math.max(hi,value);}
  const padding=Math.max((hi-lo)*.13,Math.abs(hi)*.025,1);
  lo-=padding;hi+=padding;
  const plot={left:65,right:1028,top:25,bottom:368};
  let first=dayTime(state.start),last=dayTime(state.end);
  if(first===last){first-=DAY/2;last+=DAY/2;}
  const x=day=>plot.left+(dayTime(day)-first)/(last-first)*(plot.right-plot.left);
  const y=value=>plot.bottom-(value-lo)/(hi-lo)*(plot.bottom-plot.top);
  const defs=node('defs'),clip=node('clipPath',{id:'plot-clip'});clip.append(node('rect',{x:plot.left,y:plot.top,width:plot.right-plot.left,height:plot.bottom-plot.top}));defs.append(clip);svg.append(defs);
  for(let i=0;i<=5;i++){
    const value=lo+(hi-lo)*i/5,yy=y(value);
    svg.append(node('line',{x1:plot.left,x2:plot.right,y1:yy,y2:yy,class:'grid-line'}));
    svg.append(node('text',{x:plot.left-12,y:yy+4,'text-anchor':'end',class:'axis-text'},value.toFixed(hi-lo<5?1:0)+'%'));
  }
  if(lo<0&&hi>0)svg.append(node('line',{x1:plot.left,x2:plot.right,y1:y(0),y2:y(0),class:'zero-line'}));
  const ticks=[...new Set([0,.25,.5,.75,1].map(f=>dates[Math.round((dates.length-1)*f)]))];
  for(const day of ticks)svg.append(node('text',{x:x(day),y:400,'text-anchor':'middle',class:'axis-text'},day.slice(5).replace('-','.')));
  const lines=node('g',{'clip-path':'url(#plot-clip)'});
  rows.sort((a,b)=>Number(a.id===state.selected)-Number(b.id===state.selected));
  for(const row of rows){
    const selected=row.id===state.selected,color=selected?'#0c8072':seriesColor(row.id),opacity=selected?1:(state.selected?.length ? .13 : .42);
    for(const segment of segments(row.points)){
      const path=segment.map((p,i)=>`${i?'L':'M'}${x(p.date).toFixed(2)},${y(p.cagr).toFixed(2)}`).join(' ');
      if(segment.length>1){
        const line=node('path',{d:path,stroke:color,'stroke-width':selected?3.5:1.15,opacity,class:'series-line','data-id':row.id});
        line.append(node('title',{},row.name+' · 클릭하여 강조'));lines.append(line);
      }
      if(selected||segment.length===1)for(const p of selected?segment:[segment[0]]){
        const hollow=p.status==='latest_available';
        lines.append(node('circle',{cx:x(p.date),cy:y(p.cagr),r:selected?5:2.3,fill:hollow?'white':color,stroke:color,'stroke-width':selected?2:1,opacity,class:'series-point','data-id':row.id}));
      }
    }
    if(selected){const end=row.points.filter(p=>finite(p.cagr)).at(-1);if(end)svg.append(node('text',{x:Math.min(x(end.date)+10,plot.right+8),y:Math.max(plot.top+10,Math.min(y(end.cagr)+4,plot.bottom-4)),class:'endpoint-label'},row.ticker));}
  }
  svg.append(lines);
  const cross=node('line',{id:'crosshair',x1:0,x2:0,y1:plot.top,y2:plot.bottom,stroke:'#b7c7ce','stroke-dasharray':'3 4',visibility:'hidden','pointer-events':'none'});svg.append(cross);
  chartGeometry={rows,dates,plot,x,y,first,last};
  svg.dataset.selected=state.selected??'';svg.dataset.seriesCount=String(rows.length);
}
function hover(event) {
  if(!chartGeometry)return;
  const {rows,dates,plot,x,y,first,last}=chartGeometry,rect=$('chart').getBoundingClientRect();
  const px=(event.clientX-rect.left)/rect.width*1100,py=(event.clientY-rect.top)/rect.height*430;
  if(px<plot.left||px>plot.right||py<plot.top||py>plot.bottom){$('tooltip').hidden=true;$('crosshair')?.setAttribute('visibility','hidden');return;}
  const time=first+(px-plot.left)/(plot.right-plot.left)*(last-first);
  const day=dates.reduce((best,date)=>Math.abs(dayTime(date)-time)<Math.abs(dayTime(best)-time)?date:best,dates[0]);
  const row=state.selected?rows.find(row=>row.id===state.selected):rows.reduce((best,row)=>{
    const p=row.points.find(p=>p.date===day);if(!finite(p?.cagr))return best;
    const distance=Math.abs(y(p.cagr)-py);return !best||distance<best.distance?{...row,distance}:best;
  },null);
  if(!row)return;
  const point=row.points.find(p=>p.date===day),tip=$('tooltip');tip.replaceChildren();
  tip.append(html('div','',`${row.ticker} · ${day}`),html('strong','',percent(point?.cagr)),html('small','',`실제 시세 ${point?.actualDate??'미확인'}`));
  if(point?.status==='latest_available')tip.append(html('div','','과거 가용 시세 사용'));
  if(!finite(point?.cagr))tip.append(html('div','','계산 불가 또는 미수집'));
  tip.hidden=false;
  const wrap=$('chart-wrap').getBoundingClientRect();
  tip.style.left=Math.max(5,Math.min(event.clientX-wrap.left+16,wrap.width-tip.offsetWidth-5))+'px';
  tip.style.top=Math.max(5,Math.min(event.clientY-wrap.top-tip.offsetHeight-12,wrap.height-tip.offsetHeight-5))+'px';
  const cross=$('crosshair');cross.setAttribute('x1',x(day));cross.setAttribute('x2',x(day));cross.setAttribute('visibility','visible');
}
function renderTable() {
  const row=state.index.etfs.find(row=>row.id===state.selected),body=$('observations');body.replaceChildren();
  $('more-observations').hidden=true;
  if(!row){const tr=html('tr'),td=html('td','','ETF를 선택하면 날짜별 기록을 볼 수 있습니다.');td.colSpan=5;tr.append(td);body.append(tr);$('table-note').textContent='차트 또는 목록에서 ETF를 선택해 주세요.';return;}
  const ps=points(row.id),changes=new Map();let previous=null;
  for(const p of ps){changes.set(p.date,finite(p.cagr)&&finite(previous)?p.cagr-previous:null);if(finite(p.cagr))previous=p.cagr;}
  const sorted=[...ps].reverse();
  for(const p of sorted.slice(0,state.rowsToShow)){
    const tr=html('tr'),cell=html('td'),link=html('a','',p.date);
    link.href=`https://github.com/roy888682/7emailskill/blob/main/data/etf-history/${p.date}.json`;link.target='_blank';link.rel='noopener';link.title='이 날짜의 원본 가격·수익률 데이터 확인';cell.append(link);
    const status=finite(p.cagr)?p.status==='latest_available'?'과거 가용 시세':'기준일 시세':p.status==='not_collected'?'미수집':!p.eligible?'계산 불가 / 1년 미만':'계산 불가';
    const badge=html('span','status-pill '+(!finite(p.cagr)?'missing':p.status==='latest_available'?'stale':''),status);
    const statusCell=html('td');statusCell.append(badge);
    tr.append(cell,html('td',rateClass(p.cagr),percent(p.cagr)),html('td',rateClass(changes.get(p.date)),pp(changes.get(p.date))),html('td','',p.actualDate??'—'),statusCell);body.append(tr);
  }
  $('table-note').textContent=`${row.name} · ${ps.length}일의 기록 · 수익률 차이는 %p(퍼센트포인트)입니다. 수집일을 클릭하면 정확한 원값을 확인할 수 있습니다.`;
  $('more-observations').hidden=sorted.length<=state.rowsToShow;
}

$('etf-list').addEventListener('click',event=>{const row=event.target.closest('[data-id]');if(row)select(row.dataset.id);});
$('chart').addEventListener('click',event=>{const line=event.target.closest('[data-id]');if(line)select(line.dataset.id);});
$('chart').addEventListener('pointermove',hover);
$('chart').addEventListener('pointerleave',()=>{$('tooltip').hidden=true;$('crosshair')?.setAttribute('visibility','hidden');});
$('search').addEventListener('input',event=>{state.query=event.target.value;render();});
$('countries').addEventListener('click',event=>{const button=event.target.closest('[data-country]');if(button){state.country=button.dataset.country;render();}});
$('eligible-only').addEventListener('change',event=>{state.eligibleOnly=event.target.checked;render();});
$('sort').addEventListener('change',event=>{state.sort=event.target.value;renderListForSort();});
function renderListForSort(){if(!state.index)return;state.visible=filterEtfs(state.index.etfs,{...state,latestDate:state.index.dates.at(-1)});renderList();}
$('clear-selection').addEventListener('click',()=>select(null));
$('focus-scale').addEventListener('change',event=>{state.focusScale=event.target.checked;renderChart();});
$('periods').addEventListener('click',event=>{const button=event.target.closest('[data-period]');if(!button||!state.index)return;state.period=button.dataset.period;[state.start,state.end]=rangeFor(state.index.dates,state.period);state.rowsToShow=30;loadHistory();});
for(const id of ['start-date','end-date'])$(id).addEventListener('change',()=>{
  const start=$('start-date').value,end=$('end-date').value;
  if(!start||!end||start>end){showNotice('시작일은 종료일보다 늦을 수 없습니다.',true);return;}
  if(start<state.index.dates[0]||end>state.index.dates.at(-1)){showNotice('저장된 날짜 범위 안에서 선택해 주세요.',true);return;}
  state.start=start;state.end=end;state.period='custom';state.rowsToShow=30;showNotice('');loadHistory();
});
$('more-observations').addEventListener('click',()=>{state.rowsToShow+=50;renderTable();});
$('download').addEventListener('click',()=>{
  if(!state.index)return;
  const rows=state.selected?state.visible.filter(row=>row.id===state.selected):state.visible;
  const blob=new Blob([csvFor(rows,points)],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),link=html('a');
  link.href=url;link.download=`etf-cagr-${state.selected?.replace(':','-')??'all'}-${state.start}-${state.end}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$('refresh').addEventListener('click',()=>refresh());
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
setInterval(()=>{if(!document.hidden)refresh();},300000);
window.addEventListener('hashchange',()=>{if(state.index){const id=new URLSearchParams(location.hash.slice(1)).get('etf');if(state.index.etfs.some(row=>row.id===id))select(id);}});
refresh(true);

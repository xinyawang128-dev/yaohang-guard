'use strict';
let meta, last;
const $ = id => document.getElementById(id);
const f = value => value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(2);
const svgNS = 'http://www.w3.org/2000/svg';
const failureLabels = {temperature:'温度',deadline:'时限',battery:'电量',ground_speed:'逆风导致地速不足'};

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败：' + response.status);
  return data;
}

function el(root, tag, attrs, text) {
  const e = document.createElementNS(svgNS, tag);
  for (const key in attrs) e.setAttribute(key, attrs[key]);
  if (text !== undefined) e.textContent = text;
  root.appendChild(e);
  return e;
}

function map(report) {
  const s = $('map'); s.replaceChildren();
  const xy = node => [30+meta.nodes[node][0]*46,190-meta.nodes[node][1]*43];
  const used = new Set((report?.tool_trace || []).filter(x=>x.tool==='execute_step').map(x=>x.data.route.join('-')));
  const closed = new Set(report?.config?.closed_edges || []);
  for (const [a,b,solar] of meta.edges) {
    const p=xy(a), q=xy(b), active=used.has(a+'-'+b)||used.has(b+'-'+a);
    const blocked=closed.has(a+'-'+b)||closed.has(b+'-'+a);
    el(s,'line',{x1:p[0],y1:p[1],x2:q[0],y2:q[1],stroke:blocked?'#b33d3d':active?'#087f8c':'#d2dfe5','stroke-width':active?5:2,'stroke-dasharray':blocked?'6 4':'none'});
    if (solar) el(s,'text',{x:(p[0]+q[0])/2,y:(p[1]+q[1])/2-10,'font-size':10,fill:'#718692'},'等效热暴露 +'+solar+'°C');
  }
  for (const node in meta.nodes) {
    const p=xy(node), current=report?.verification?.node===node;
    el(s,'circle',{cx:p[0],cy:p[1],r:current?14:11,fill:current?'#087f8c':node==='D'?'#183f54':'#fff',stroke:'#087f8c','stroke-width':2});
    el(s,'text',{x:p[0],y:p[1]+4,'text-anchor':'middle','font-size':12,fill:current||node==='D'?'#fff':'#183f54'},node);
    el(s,'text',{x:p[0],y:p[1]+28,'text-anchor':'middle','font-size':11,fill:'#607581'},node==='A'?'出发仓':node==='D'?'交付点':node==='R'?'人工接管点':'航路节点');
  }
}

function chart(report) {
  const s=$('chart'); s.replaceChildren();
  const data=report.history || [], lower=report.config.lower_c, upper=report.config.upper_c;
  if (!data.length) { el(s,'text',{x:70,y:110,fill:'#607581'},'任务未起飞，无执行温度轨迹'); return; }
  const maxT=Math.max(upper+2,...data.map(p=>p.temperature_c+1));
  const minT=Math.min(lower-2,...data.map(p=>p.temperature_c-1));
  const maxX=Math.max(1,data[data.length-1].time_min);
  const x=t=>45+t/maxX*360, y=t=>195-(t-minT)/(maxT-minT)*165;
  el(s,'rect',{x:45,y:y(upper),width:360,height:y(lower)-y(upper),fill:'#e7f5ee'});
  for (const value of [lower,(lower+upper)/2,upper]) {
    el(s,'line',{x1:45,x2:405,y1:y(value),y2:y(value),stroke:'#96b1b8','stroke-dasharray':'4 4'});
    el(s,'text',{x:3,y:y(value)+4,fill:'#607581','font-size':11},f(value)+'°C');
  }
  el(s,'polyline',{points:data.map(p=>x(p.time_min)+','+y(p.temperature_c)).join(' '),fill:'none',stroke:'#087f8c','stroke-width':3,'stroke-dasharray':report.verification.sensor_ok?'none':'5 3'});
  for (const value of [0,maxX/2,maxX]) el(s,'text',{x:x(value),y:222,'text-anchor':'middle',fill:'#607581','font-size':11},f(value)+' min');
}

function render(report, source) {
  const r=report;
  if (!r.verification || !Array.isArray(r.tool_trace) || !Array.isArray(r.initial_candidates)) throw new Error('导出结构不完整，请使用修订版工程重新测试并导出。');
  last=r;
  $('modeBanner').textContent=source==='saved'
    ? 'MCP 工具导出的合成仿真结果 · Agnes 参与情况须核对官方 AGH 原始会话，本页面不认证模型身份。'
    : '离线合成仿真 · 本次未调用 AGH 或 Agnes 模型，可用于工程检查与理解。';
  $('status').textContent=({DELIVERED:'已交付',ABORTED:'已停止',FAILED:'验证失败',UNVERIFIED:'无法验证',INCOMPLETE:'未完成'})[r.verification.status] || r.verification.status;
  for (const [id,key] of [['time','time_min'],['energy','energy_wh'],['temp','temperature_c']]) $(id).textContent=f(r.verification[key]);
  const steps=r.tool_trace.filter(t=>t.tool==='execute_step');
  const actual=steps.length?[steps[0].data.route[0],...steps.map(t=>t.data.route[1])].join(' → '):'未起飞';
  $('resultTitle').textContent=(r.title || r.case_id || r.scenario || '自定义任务')+' · '+actual;
  const events=r.tool_trace.filter(t=>t.tool==='inject_event').length;
  const replans=r.tool_trace.filter(t=>t.tool==='plan_candidates' && t.data.current_node!=='A').length;
  $('reason').textContent=(r.verification.reason || '当前状态已完成工具验证。')+' 已注入 '+events+' 个异常；途中规划 '+replans+' 次。'+(!r.verification.sensor_ok?' 温度为仿真值，传感器失效后不能作为观测证明。':'');
  map(r); chart(r);
  $('chartLegend').textContent='虚线窗口：'+r.config.lower_c+'–'+r.config.upper_c+'°C；曲线为合成仿真'+(!r.verification.sensor_ok?'，传感器失效，非实测读数':'')+'。';
  $('plans').replaceChildren();
  for (const p of r.initial_candidates) {
    const tr=document.createElement('tr');
    const cells=[p.route.join(' → ')+' / '+(p.pack==='enhanced'?'加强保温':'标准保温'),f(p.nominal.peak_c)+'°C',f(p.robust.peak_max_c)+'°C',f(p.robust.time_max_min)+' min',f(p.robust.energy_max_wh)+' Wh',p.robust.feasible?'通过':p.robust.failures.map(x=>failureLabels[x] || x).join('、')];
    cells.forEach((text,index)=>{const td=document.createElement('td');td.textContent=text;if(index===5)td.style.color=p.robust.feasible?'#207349':'#b33d3d';tr.append(td);});
    $('plans').append(tr);
  }
  const baseline=r.baseline_shortest_standard, same=r.same_pack_shortest, mc=r.monte_carlo_initial;
  $('comparison').textContent=(baseline?'最短航路＋标准包装的角点验证：'+(baseline.robust.feasible?'通过':'未通过')+'。':'')+(same?'同包装最短航路角点验证：'+(same.robust.feasible?'通过':'未通过')+'。':'')+(mc?'初始计划合成扰动 '+mc.samples+' 次，失败 '+mc.failures+' 次；不等于真实可靠性。':'');
  $('trace').replaceChildren();
  for (const t of r.tool_trace.filter(x=>!['simulate_plan','verify_delivery'].includes(x.tool))) {
    const div=document.createElement('div'), body=document.createElement('div'), title=document.createElement('b'), desc=document.createElement('span');
    div.className='step'; title.textContent=t.sequence+' · '+t.tool; body.append(title,document.createElement('br'));
    desc.textContent=t.tool==='execute_step'?t.data.route.join(' → ')+'，仿真峰温 '+f(t.data.observation.peak_c)+'°C':t.tool==='inject_event'?t.data.type+'：'+JSON.stringify(t.data.value):t.tool==='abort_task'?t.data.reason:t.tool==='plan_candidates'?'从 '+t.data.current_node+' 检查 '+t.data.candidates.length+' 个剩余计划':'创建物理约束与温度窗口';
    body.append(desc);div.append(body);$('trace').append(div);
  }
  $('json').textContent=JSON.stringify(r,null,2);$('download').disabled=false;
}

async function refreshSaved() {
  $('refreshSaved').disabled=true;$('loadSaved').disabled=true;$('error').textContent='';
  const previous=$('saved').value;
  try {
    const reports=await request('/api/agh-reports');
    $('saved').replaceChildren();
    if (!reports.length) {
      const opt=document.createElement('option');opt.value='';opt.textContent='尚无导出：请在 AGH 调用 export_evidence';$('saved').append(opt);
    } else {
      for (const r of reports) { const opt=document.createElement('option');opt.value=r.task_id;opt.textContent=r.title+' · '+r.status+' · '+r.task_id;$('saved').append(opt); }
      if (reports.some(r=>r.task_id===previous)) $('saved').value=previous;
      $('loadSaved').disabled=false;
    }
  } catch (error) { $('error').textContent=error.message; }
  finally { $('refreshSaved').disabled=false; }
}

$('scenario').onchange=()=>{const c={...meta.defaults,...meta.scenarios[$('scenario').value].config};for(const [id,key] of [['ambient','ambient_c'],['wind','headwind_ms'],['battery','battery_wh'],['deadline','deadline_min']])$(id).value=c[key];};
$('run').onclick=async()=>{
  $('run').disabled=true;$('error').textContent='';
  try { render(await request('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario:$('scenario').value,overrides:{ambient_c:Number($('ambient').value),headwind_ms:Number($('wind').value),battery_wh:Number($('battery').value),deadline_min:Number($('deadline').value)}})}),'offline'); }
  catch(error){$('error').textContent=error.message;}
  finally{$('run').disabled=false;}
};
$('refreshSaved').onclick=refreshSaved;
$('loadSaved').onclick=async()=>{
  const id=$('saved').value;if(!id)return;
  $('loadSaved').disabled=true;$('error').textContent='';
  try { render(await request('/api/report?task_id='+encodeURIComponent(id)),'saved'); }
  catch(error){$('error').textContent=error.message;}
  finally{$('loadSaved').disabled=!$('saved').value;}
};
$('download').onclick=()=>{
  if(!last)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(last,null,2)],{type:'application/json'})), a=document.createElement('a');
  a.href=url;a.download='yaohang-'+(last.case_id || last.scenario || 'custom')+'-'+last.task_id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
$('run').disabled=true;$('loadSaved').disabled=true;
request('/api/meta').then(async m=>{
  meta=m;
  for(const [id,s] of Object.entries(m.scenarios)){const opt=document.createElement('option');opt.value=id;opt.textContent=s.title;$('scenario').append(opt);}
  map();$('scenario').onchange();$('run').disabled=false;await refreshSaved();
}).catch(error=>{$('error').textContent=error.message;});

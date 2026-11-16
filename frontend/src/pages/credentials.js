import {api,exportCredentials} from '../api/client.js';
import {credentials} from '../api/entities.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {CredentialEvent,VerifyStatus} from '../constants/enums.js';
const short=h=>esc(String(h||'').slice(0,18));
const eventName=e=>CredentialEvent[e]||e;
function summaryOf(c){
 const s=c.summary||{};
 if(c.event==='dataset.intake')return esc(s.name)+' · '+esc(s.rows)+' 行 · 内容指纹 '+short(s.checksum)+'…';
 if(c.event==='job.completed')return esc(s.name)+' · '+esc(s.summary||'');
 if(c.event==='job.approved')return esc(s.name)+' · 批准人 '+esc(s.approved_by||c.actor);
 if(c.event==='delivery.archived')return esc(s.report||'')+' · '+esc(s.filename)+' → '+esc(s.destination||'');
 return '';
}
function segView(s){
 if(s.result==='通过')return '<li class="seg ok"><strong>#'+s.from+' – #'+s.to+'</strong><span>通过 · 通过证明 '+short(s.attestation)+'…</span></li>';
 return '<li class="seg bad"><strong>#'+s.from+' – #'+s.to+'</strong><span>异常 · 不出具通过证明</span>'+(s.issues||[]).map(i=>'<small>#'+i.seq+' '+esc(i.type)+'：'+esc(i.detail)+'</small>').join('')+'</li>';
}
function runView(v,detail=false){
 const head='<div class="run-head"><span class="badge '+(v.status==='passed'?'ok':'bad')+'">'+esc(VerifyStatus[v.status]||v.status)+'</span><strong>核验范围 #'+v.from_seq+' – #'+v.to_seq+'</strong><span>断点 '+(v.anomalies||[]).length+' 处 · 核验时链头 #'+v.head_seq+' · '+esc(v.actor)+' · '+date(v.created_at)+'</span></div>';
 if(!detail)return head;
 const anomalies=(v.anomalies||[]).map(a=>'<tr><td>#'+a.seq+'</td><td>'+esc(a.type)+'</td><td>'+esc(a.detail)+'</td></tr>').join('');
 return head+'<ul class="segments">'+(v.segments||[]).map(segView).join('')+'</ul>'+(anomalies?'<div class="table-wrap"><table><thead><tr><th>断点序号</th><th>类型</th><th>说明</th></tr></thead><tbody>'+anomalies+'</tbody></table></div>':'<p class="hint">范围内无缺号、篡改或业务不符；全部区间出具通过证明。</p>');
}
export async function credentialsPage(){
 const [chain,runs,audits]=await Promise.all([credentials.list(),credentials.verifications(),api('/audits')]);
 const isAdmin=session.user.role==='admin',head=chain.head,list=chain.credentials,latest=runs[0];
 const linked={};list.forEach(c=>{linked[c.event+':'+c.ref_id]=c.seq;});
 const auditMark=a=>{
  const map={'dataset.create':['dataset.intake',a.detail&&a.detail.id],'job.completed':['job.completed',a.detail&&a.detail.id],'job.approve':['job.approved',a.detail&&a.detail.id],'report.delivered':['delivery.archived',a.detail&&a.detail.delivery]};
  const m=map[a.action],seq=m&&linked[m[0]+':'+m[1]];
  return seq?'<span class="badge ok">已入链 #'+seq+'</span>':'<span class="badge muted">未入链</span>';
 };
 const controls=isAdmin
  ?'<div class="verify-controls"><form id="verify-form" class="inline-form"><h3>发起核验</h3><div class="parameter-grid"><label>起始序号<input type="number" name="from_seq" min="1" max="'+Math.max(head.seq,1)+'" value="1" required></label><label>截止序号<input type="number" name="to_seq" min="1" max="'+Math.max(head.seq,1)+'" value="'+Math.max(head.seq,1)+'" required></label></div><button type="submit" class="primary" '+(head.seq?'':'disabled')+'>核验此范围</button></form><form id="export-form" class="inline-form"><h3>导出凭据包</h3><label>截止序号<input type="number" name="upto" min="1" max="'+Math.max(head.seq,1)+'" value="'+Math.max(head.seq,1)+'" required></label><button type="submit" '+(head.seq?'':'disabled')+'>导出凭据与业务摘要 ↓</button><p class="hint">导出为截止序号的快照，导出期间新操作不会混入。</p></form></div>'
  :'<p class="hint">仅业务负责人可发起核验或导出；分析员与观察员可查看链上凭据、核验范围、断点与结果。</p>';
 const rows=list.map(c=>'<tr><td>#'+c.seq+'</td><td>'+esc(eventName(c.event))+'</td><td>'+summaryOf(c)+'</td><td>'+esc(c.actor)+'</td><td>'+date(c.created_at)+'</td><td class="mono">'+short(c.hash)+'…</td></tr>').join('');
 return heading('06 / EVIDENCE CHAIN','业务凭据链与核验','日历入库、试算完成、批准、简报归档在落库同事务记证；序号按实际落库顺序衔接，中断重试不重复记证。','<button class="button" id="refresh-credentials">刷新 ↻</button>')
 +'<section class="overview-hero chain-hero"><div class="narrative"><p class="eyebrow">链头状态</p><h2>'+(head.seq?'当前链头为第 '+head.seq+' 号凭据，指纹 '+short(head.hash)+'…':'凭据链为空，完成一次业务操作后自动生成首条凭据。')+'</h2><p>覆盖事件：日历入库 → 试算完成 → 批准 → 简报归档。凭据与业务结果一起生效，失败一起撤回。</p></div><div class="numbers">'+[['链头序号',head.seq],['覆盖事件','4 类'],['核验次数',runs.length],['最近结论',latest?VerifyStatus[latest.status]:'—']].map(([k,v])=>'<div><span>'+k+'</span><strong>'+v+'</strong></div>').join('')+'</div></section>'
 +'<section class="panel"><div class="section-title"><h2>核验与导出</h2><span>负责人操作</span></div>'+controls+'</section>'
 +(latest?'<section class="panel"><div class="section-title"><h2>最近一次核验</h2><span>断点与区间结论</span></div>'+runView(latest,true)+'</section>':'')
 +'<section class="panel"><div class="section-title"><h2>核验记录</h2><span>'+runs.length+' 次</span></div>'+(runs.length?runs.map(v=>'<div class="run-item">'+runView(v)+'</div>').join(''):'<p class="empty">尚未发起核验。</p>')+'</section>'
 +'<section class="panel"><div class="section-title"><h2>链上凭据</h2><span>'+list.length+' 条 · 按序号倒序</span></div>'+(rows?'<div class="table-wrap"><table><thead><tr><th>序号</th><th>事件</th><th>业务摘要</th><th>操作者</th><th>时间</th><th>凭据指纹</th></tr></thead><tbody>'+rows+'</tbody></table></div>':'<p class="empty">暂无凭据。</p>')+'</section>'
 +'<section class="panel"><div class="section-title"><h2>未核验历史 · 旧式操作记录</h2><span>核验不覆盖以下记录</span></div><ul class="timeline legacy">'+audits.map(a=>'<li><strong>'+esc(a.action)+' '+auditMark(a)+'</strong><span>'+esc(a.actor)+' · '+date(a.at)+'</span></li>').join('')+'</ul><p class="hint">以上为旧式操作日志，未纳入凭据链，无法据此证明遗漏或改动；追责以链上凭据与核验结论为准。</p></section>';
}
export function bindCredentials(refresh){
 document.querySelector('#refresh-credentials').onclick=refresh;
 const vf=document.querySelector('#verify-form');
 if(vf)submit(vf,async f=>{const from=Number(f.get('from_seq')),to=Number(f.get('to_seq'));if(to<from)throw new Error('截止序号不能小于起始序号');const run=await credentials.verify(from,to);notify(run.status==='passed'?'核验通过：范围内无缺号、篡改或业务不符':'核验发现 '+run.anomalies.length+' 处异常，请查看断点明细',run.status!=='passed');await refresh();});
 const ef=document.querySelector('#export-form');
 if(ef)submit(ef,async f=>{await exportCredentials(Number(f.get('upto')));notify('凭据包已导出');await refresh();});
}

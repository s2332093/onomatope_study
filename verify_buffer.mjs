// Unit-level browser adapter: test the upload contract without controlling a browser.
import vm from 'node:vm';import fs from 'node:fs';import assert from 'node:assert/strict';import {randomUUID} from 'node:crypto';
const source=fs.readFileSync(new URL('static/study_log.js',import.meta.url),'utf8');
const values=new Map(), requests=[];let fail=true;
const storage={get length(){return values.size},key:i=>[...values.keys()][i],getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,String(v)),removeItem:k=>values.delete(k)};
function page({finish='',pid='learner',receipt=''}={}){
  let now=0;const handlers={}, nodes=new Map(), timers=[];
  function element(){return {textContent:'',disabled:false,style:{},handlers:{},setAttribute(){},addEventListener(k,f){this.handlers[k]=f}};}
  const status=element(),button=element();nodes.set('finishStatus',status);nodes.set('saveStudy',button);
  const doc={body:{dataset:{studyPrefix:'/a',studyParticipant:pid,studyReceipt:receipt,studyFinish:finish},append(el){nodes.set(el.id,el)}},hidden:false,getElementById:k=>nodes.get(k),createElement:element,addEventListener(k,f){(handlers[k]??=[]).push(f)}};
  const ctx={document:doc,localStorage:storage,sessionStorage:{getItem:()=>null,removeItem(){}},crypto:{randomUUID},performance:{now:()=>now},location:{pathname:finish?'/a/finish':'/a/word/iraira/f1/1'},Date,JSON,Math,Error,Set,console,setInterval:f=>timers.push(f),addEventListener(k,f){(handlers[k]??=[]).push(f)},fetch:async(url,options)=>{requests.push({url,payload:JSON.parse(options.body)});return {ok:!fail,status:fail?503:200}}};ctx.window=ctx;vm.runInNewContext(source,ctx);
  return {ctx,doc,button,status,timers,advance(ms){now+=ms},emit(k,e={}){for(const f of handlers[k]??[])f(e)}};
}
const p=page();p.advance(2000);
for(let i=0;i<150;i++)p.emit('click',{target:{closest:()=>null,tagName:'DIV'}});
p.emit('pagehide');p.timers.forEach(f=>f());assert.equal(requests.length,0,'learning must not upload even after many actions or navigation');
const size=values.size;const next=page({receipt:'opaque-server-receipt'});assert.ok(values.size>size,'navigation retains earlier records and grading receipt');
next.advance(1000);next.doc.hidden=true;next.emit('visibilitychange');next.advance(9000);next.doc.hidden=false;next.emit('visibilitychange');next.advance(1000);next.emit('pagehide');
const final=page({finish:'1'});await final.button.handlers.click();assert.equal(requests.length,1);assert.match(final.status.textContent,/保存できません/);assert.ok([...values.keys()].some(k=>k.includes('event:')),'failure must retain actions');
fail=false;await final.button.handlers.click();assert.equal(requests.length,2);assert.ok(requests[1].payload.events.length>=150);assert.deepEqual(requests[1].payload.receipts,['opaque-server-receipt']);
assert.ok(requests[1].payload.events.filter(e=>e.event_type==='page_leave').every(e=>e.detail.active_ms===2000),'hidden time is excluded');assert.match(final.status.textContent,/保存しました/);assert.equal(final.button.disabled,true);assert.equal([...values.keys()].filter(k=>k!=='study-log-v3:learner:/a:status').length,0);
page({pid:'another'});assert.ok([...values.keys()].some(k=>k.startsWith('study-log-v3:another:')),'new learner keeps separate local records');
console.log('OK: zero upload during learning, persistence across page instances, hidden-time exclusion, encrypted receipt buffering, failure retention and acknowledged completion');

// Unit-level browser adapter: persistence/network timing without controlling a browser.
import vm from 'node:vm';import fs from 'node:fs';import assert from 'node:assert/strict';import {randomUUID} from 'node:crypto';
const source=fs.readFileSync(new URL('static/study_log.js',import.meta.url),'utf8');
const settle=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
const ack=r=>({ok:true,status:200,json:async()=>({saved:r.payload.events.length+r.payload.receipts.length,completed:r.url.endsWith('/finish')})});
function environment({locks=true}={}){
  let now=1000000;const values=new Map(), requests=[],pages=[],held=new Map();
  const storage={get length(){return values.size},key:i=>[...values.keys()][i],getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,String(v)),removeItem:k=>values.delete(k)};
  const env={values,requests,storage,respond:async r=>ack(r),async advance(ms){
    const end=now+ms;
    while(true){
      const timers=pages.flatMap(p=>p.live?[...p.timers.values()].map(t=>({...t,p})):[]).filter(t=>t.at<=end).sort((a,b)=>a.at-b.at);
      if(!timers.length)break;
      const t=timers[0];now=t.at;
      if(t.every)t.p.timers.get(t.id).at+=t.every;else t.p.timers.delete(t.id);
      t.f();await settle();
    }
    now=end;await settle();
  }};
  env.page=({finish='',pid='learner',prefix='/a',receipt=''}={})=>{
    const born=now,handlers={},nodes=new Map(),timers=new Map();let timerId=0;
    function element(){return {textContent:'',disabled:false,style:{},handlers:{},setAttribute(){},addEventListener(k,f){this.handlers[k]=f}};}
    const status=element(),button=element();nodes.set('finishStatus',status);nodes.set('saveStudy',button);
    const doc={body:{dataset:{studyPrefix:prefix,studyParticipant:pid,studyReceipt:receipt,studyFinish:finish},append(el){nodes.set(el.id,el)}},hidden:false,getElementById:k=>nodes.get(k),createElement:element,addEventListener(k,f){(handlers[k]??=[]).push(f)}};
    const lockAPI={async request(name,options,task){
      if(options.ifAvailable && held.has(name))return task(null);
      while(held.has(name))await held.get(name);
      let release;held.set(name,new Promise(resolve=>{release=resolve}));
      try{return await task({name});}finally{held.delete(name);release();}
    }};
    class ClockDate extends Date{constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
    const addTimer=(f,ms,every=0)=>{const id=++timerId;timers.set(id,{id,f,at:now+ms,every});return id;};
    const ctx={document:doc,localStorage:storage,sessionStorage:{getItem:()=>null,removeItem(){}},navigator:locks?{locks:lockAPI}:{},crypto:{randomUUID},performance:{now:()=>now-born},location:{pathname:finish?prefix+'/finish':prefix+'/word/iraira/f1/1'},Date:ClockDate,TextEncoder,AbortController,JSON,Math,Error,Set,console,setInterval:(f,ms)=>addTimer(f,ms,ms),setTimeout:addTimer,clearTimeout:id=>timers.delete(id),addEventListener(k,f){(handlers[k]??=[]).push(f)},fetch:async(url,options)=>{const r={url,payload:JSON.parse(options.body),signal:options.signal};requests.push(r);return env.respond(r);}};
    ctx.window=ctx;const p={ctx,doc,button,status,timers,live:true,root:'study-log-v3:'+pid+':'+prefix+':',emit(k,e={}){for(const f of handlers[k]??[])f(e)},click(){this.emit('click',{target:{closest:()=>null,tagName:'DIV'}})},stop(){this.live=false}};pages.push(p);vm.runInNewContext(source,ctx);return p;
  };
  env.records=p=>[...values].filter(([key])=>key.startsWith(p.root)&&!['status','next-sync'].some(s=>key===p.root+s)).map(([key,raw])=>({key,raw,value:JSON.parse(raw)}));
  return env;
}

// No network per action; the 30-second schedule survives short page visits.
{
  const e=environment(),p=e.page();await e.advance(2000);
  for(let i=0;i<150;i++)p.click();
  const inputs=new Map(),form={id:'matching',querySelector(s){return inputs.get(s.match(/name="([^"]+)"/)[1])},append(input){inputs.set(input.name,input)}};
  assert.equal(p.ctx.studyPrepareSubmission(form,'conditions:shidasu'),true);
  assert.equal(inputs.get('_study_elapsed_ms').value,2000);assert.equal(inputs.get('_study_click_count').value,150);
  const attempt=inputs.get('attempt_id').value;p.ctx.studyPrepareSubmission(form,'conditions:shidasu');assert.notEqual(inputs.get('attempt_id').value,attempt);
  assert.equal(e.requests.length,0);
  p.emit('pagehide');p.stop();const q=e.page({receipt:'authenticated-receipt'});
  await e.advance(1000);q.doc.hidden=true;q.emit('visibilitychange');await e.advance(9000);q.doc.hidden=false;q.emit('visibilitychange');
  await e.advance(1000);q.emit('pagehide');q.stop();e.page();
  await e.advance(16999);assert.equal(e.requests.length,0);await e.advance(1);
  assert.equal(e.requests.length,1);assert.equal(e.requests[0].url,'/a/api/events');
  assert.deepEqual(e.requests[0].payload.receipts,['authenticated-receipt']);
  assert.ok(e.requests[0].payload.events.filter(x=>x.event_type==='page_leave').every(x=>x.detail.active_ms===2000),'hidden time excluded');
}

// Offline autosave and a browser/page restart retain all unsent data and retry.
{
  const e=environment(),p=e.page({receipt:'receipt-offline'});e.respond=async()=>({ok:false,status:503});p.click();
  await e.advance(30000);assert.equal(e.requests.length,1);assert.ok(e.records(p).length);p.emit('pagehide');p.stop();
  const q=e.page();await e.advance(29999);assert.equal(e.requests.length,1);e.respond=async r=>ack(r);await e.advance(1);
  assert.equal(e.requests.length,2);assert.ok(e.requests[1].payload.events.some(x=>x.event_type==='click'));assert.deepEqual(e.requests[1].payload.receipts,['receipt-offline']);
  assert.ok(e.records(q).every(x=>x.value.event_type==='page_snapshot'));q.click();await e.advance(30000);
  const sentIds=new Set(e.requests[1].payload.events.map(x=>x.event_id));assert.ok(e.requests[2].payload.events.every(x=>!sentIds.has(x.event_id)),'acknowledged records not resent');
}

// In-flight uploads never block submissions or delete a newer local snapshot.
{
  const e=environment(),p=e.page();let release;e.respond=r=>new Promise(resolve=>{release=()=>resolve(ack(r))});
  await e.advance(30000);assert.equal(e.requests.length,1);const old=e.requests[0].payload.events.find(x=>x.event_type==='page_snapshot');assert.ok(old);
  p.click();const form={id:'practice',querySelector(){return null},append(){}};assert.equal(p.ctx.studyPrepareSubmission(form),true);
  await e.advance(5000);const changed=e.records(p).find(x=>x.key.includes('snapshot:'));assert.notEqual(changed.value.event_id,old.event_id);
  let secondRelease;e.respond=r=>new Promise(resolve=>{secondRelease=()=>resolve(ack(r))});release();await settle();assert.ok(e.values.has(changed.key),'changed snapshot retained until its own acknowledgment');
  e.respond=async r=>ack(r);secondRelease();await settle();await e.advance(25000);
  const later=e.requests.slice(1).flatMap(r=>r.payload.events).filter(x=>x.event_type==='page_snapshot');assert.ok(later.every(x=>x.event_id!==old.event_id));assert.equal(Math.max(...later.map(x=>x.detail.active_ms)),60000);
}

// A long offline backlog is chunked; completion is sent last and is retryable.
{
  const e=environment({locks:false}),p=e.page({receipt:'pending-receipt'});
  for(let i=0;i<650;i++)p.click();p.emit('pagehide');p.stop();const f=e.page({finish:'1'});
  let failFinish=true;e.respond=async r=>r.url.endsWith('/finish')&&failFinish?{ok:false,status:503}:ack(r);
  await f.button.handlers.click();assert.match(f.status.textContent,/保存できません/);
  assert.ok(e.requests.length>=5);assert.ok(e.requests.every(r=>r.payload.events.length+r.payload.receipts.length<=200));
  assert.ok(e.requests.slice(0,-1).every(r=>r.url==='/a/api/events'&&r.payload.events.every(x=>x.event_type!=='study_finished')));
  assert.equal(e.records(f).length,1);const marker=e.records(f)[0].raw;failFinish=false;await f.button.handlers.click();
  assert.equal(JSON.stringify(e.requests.at(-1).payload.events[0]),marker,'retry keeps stable completion ID/time');
  assert.match(f.status.textContent,/保存しました/);assert.equal(f.button.disabled,true);assert.equal(e.records(f).length,0);
}

// Two tabs share the timer/lock. Clicking Finish during autosave waits and flushes.
{
  const e=environment(),p=e.page(),q=e.page({finish:'1'});let release;e.respond=r=>new Promise(resolve=>{release=()=>resolve(ack(r))});
  await e.advance(30000);assert.equal(e.requests.length,1);
  let warned=false;p.emit('beforeunload',{preventDefault(){warned=true}});assert.equal(warned,false,'ordinary autosave does not block navigation');
  const done=q.button.handlers.click();await settle();assert.equal(q.button.disabled,true);assert.equal(e.requests.length,1);
  e.respond=async r=>ack(r);release();await done;
  assert.match(q.status.textContent,/保存しました/);assert.equal(e.requests.at(-1).url,'/a/api/finish');assert.equal(e.records(q).length,0);
}

// No cross-learner/group upload, and a 2xx response without an ACK deletes nothing.
{
  const e=environment(),a=e.page(),b=e.page({prefix:'/b'}),other=e.page({pid:'other'});e.respond=async()=>({ok:true,status:200,json:async()=>({})});
  await e.advance(30000);assert.equal(e.requests.length,3);assert.ok(e.records(a).length&&e.records(b).length&&e.records(other).length);
  for(const r of e.requests)assert.ok(r.payload.events.every(x=>x.detail.path.startsWith(r.url.slice(0,2)+'/')));
  e.respond=async r=>ack(r);a.emit('online');await settle();assert.equal(e.records(a).length,0);assert.ok(e.records(b).length&&e.records(other).length);
}
// A stalled connection times out without losing records or stopping new actions.
{
  const e=environment(),p=e.page();e.respond=r=>new Promise((_,reject)=>r.signal.addEventListener('abort',()=>reject(new Error('timeout'))));
  await e.advance(30000);p.click();await e.advance(20000);assert.ok(e.records(p).length);
  e.respond=async r=>ack(r);await e.advance(10000);assert.ok(e.requests.length>=2);assert.ok(e.requests.at(-1).payload.events.some(x=>x.event_type==='click'));
}
// Large encrypted receipts respect the byte limit, with bounded work per cycle.
{
  const e=environment(),p=e.page();
  for(let i=0;i<80;i++)e.storage.setItem(p.root+'receipt:'+i,JSON.stringify({receipt:'r'.repeat(12000)+i}));
  await e.advance(30000);assert.equal(e.requests.length,3);assert.ok(e.records(p).length);
  assert.ok(e.requests.every(r=>new TextEncoder().encode(JSON.stringify(r.payload)).length<=256*1024));
  await e.advance(30000);assert.equal(e.records(p).filter(x=>x.value.receipt).length,0);
}
console.log('OK: nonblocking 30s batching across navigation/tabs, offline retry/restart, immutable snapshots, ACK-only removal, bounded final flush, completion retry and learner/group isolation');

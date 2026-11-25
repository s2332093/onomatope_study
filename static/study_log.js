(() => {
  const {studyPrefix:prefix, studyParticipant:participant, studyReceipt:receipt, studyFinish:finish} = document.body.dataset;
  if (!prefix || !participant) return;
  const pageId=crypto.randomUUID(), started=performance.now();
  const root='study-log-v3:'+participant+':'+prefix+':', statusKey=root+'status';
  // Outside the v3 record namespace so an already-open older tab ignores it.
  const syncKey='study-log-sync-v1:'+participant+':'+prefix;
  const SYNC_MS=30000, MAX_BATCH_RECORDS=200, MAX_BATCH_BYTES=256*1024;
  let sequence=0,clicks=0,activeMs=0,activeSince=document.hidden?null:performance.now(),storageOk=true,sending=false,finishing=false;
  const text=document.getElementById('finishStatus'), button=document.getElementById('saveStudy');
  function notice(message) {
    let el=document.getElementById('studySaveStatus');
    if(!el){el=document.createElement('p');el.id='studySaveStatus';el.setAttribute('role','status');el.style.cssText='position:fixed;bottom:8px;right:12px;z-index:1000;background:#fff4df;border:1px solid #e8890c;padding:10px;border-radius:8px;max-width:380px;font-size:13px';document.body.append(el);}
    el.textContent=message;
  }
  function put(key,value){try{localStorage.setItem(root+key,JSON.stringify(value));return true;}catch(_){storageOk=false;notice('このブラウザに記録を保存できません。学習を進めず、実施者に知らせてください。');return false;}}
  function status(){try{return localStorage.getItem(statusKey);}catch(_){storageOk=false;return null;}}
  function active(){return activeMs+(activeSince===null?0:performance.now()-activeSince);}
  function pause(){if(activeSince!==null)activeMs+=performance.now()-activeSince;activeSince=null;}
  function event(type,detail={},snapshot=false){
    if(finish || status())return;
    const id=pageId+':'+sequence++;
    // Replace the local snapshot, but give each revision an immutable upload ID.
    // A later snapshot must not conflict with one already saved by autosave.
    put(snapshot?'snapshot:'+pageId:'event:'+id,{event_id:id,page_id:pageId,client_time:new Date().toISOString(),elapsed_ms:Math.round(performance.now()-started),event_type:type,detail:{...detail,path:location.pathname,active_ms:Math.round(active()),click_count:clicks}});
  }
  window.studyEvent=event;
  window.studyRecordReceipt=token=>{if(token)put('receipt:'+crypto.randomUUID(),{receipt:token});};
  if(receipt)window.studyRecordReceipt(receipt);
  // Keep the same storage namespace so upgrading preserves unsent records.
  try {
    const legacyKey='study-events-v2:'+participant+':'+prefix;
    const legacy=JSON.parse(sessionStorage.getItem(legacyKey)||'[]');
    for(const old of legacy)if(old.event_id)put('legacy:'+old.event_id,old);
    sessionStorage.removeItem(legacyKey);
  }catch(_){storageOk=false;}
  function pending(){
    const items=[];
    for(let i=0;i<localStorage.length;i++){
      const key=localStorage.key(i);
      if(key?.startsWith(root) && key!==statusKey && key!==syncKey){const raw=localStorage.getItem(key);if(raw!==null)items.push({key,raw,value:JSON.parse(raw)});}
    }
    return items;
  }
  function batchOf(items){
    const batch=[];let bytes=200;
    for(const item of items){
      const size=new TextEncoder().encode(item.raw).length+1;
      if(batch.length && (batch.length>=MAX_BATCH_RECORDS || bytes+size>MAX_BATCH_BYTES))break;
      batch.push(item);bytes+=size;
    }
    return batch;
  }
  async function upload(batch,completed=false){
    const events=batch.filter(x=>!x.value.receipt).map(x=>x.value), receipts=batch.filter(x=>x.value.receipt).map(x=>x.value.receipt);
    const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),20000);
    try{
      const response=await fetch(prefix+(completed?'/api/finish':'/api/events'),{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({participant_id:participant,events,receipts})});
      if(!response.ok){const error=new Error('save failed');error.status=response.status;throw error;}
      const ack=await response.json();
      if(ack.saved!==batch.length || (completed && ack.completed!==true))throw new Error('missing acknowledgment');
      // Another page or a snapshot tick may have updated a key during the request.
      for(const item of batch)if(localStorage.getItem(item.key)===item.raw)localStorage.removeItem(item.key);
    }finally{clearTimeout(timeout);}
  }
  function locked(task,automatic=false){
    // Web Locks serializes tabs of the same learner. IDs also make resends safe
    // in browsers without Web Locks, or when a response is lost after commit.
    if(navigator.locks?.request)return navigator.locks.request(root+'upload',automatic?{ifAvailable:true}:{},lock=>lock?task():undefined);
    return task();
  }
  async function autosave(){
    if(sending || finishing || !storageOk || status()==='saving')return;
    try{
      await locked(async()=>{
        if(Date.now()<Number(localStorage.getItem(syncKey)||0))return;
        // Shared across page navigations and tabs; a new page does not restart it.
        localStorage.setItem(syncKey,String(Date.now()+SYNC_MS));
        sending=true;
        try{
          for(let i=0;i<3;i++){
            if(status()==='saving')break;
            const batch=batchOf(pending().filter(x=>x.key!==root+'finish'));
            if(!batch.length)break;
            await upload(batch);
          }
        }finally{sending=false;}
      },true);
    }catch(_){/* Keep every unacknowledged record locally; retry next cycle. */}
    if(!sending && !finishing)refresh();
  }
  try{
    if(!localStorage.getItem(syncKey))localStorage.setItem(syncKey,String(Date.now()+SYNC_MS));
    setTimeout(autosave,Math.max(1000,Math.min(SYNC_MS,Number(localStorage.getItem(syncKey))-Date.now())));
  }catch(_){storageOk=false;}
  setInterval(()=>{if(!finish && !document.hidden)event('page_snapshot',{},true);void autosave();},5000);
  addEventListener('online',()=>{try{localStorage.setItem(syncKey,'0');void autosave();}catch(_){}});
  function refresh(){
    if(!finish)return;
    try{
      const items=pending();
      if(status()==='saved' && !items.length){text.textContent='学習記録を保存しました。この画面を閉じてかまいません。';button.disabled=true;button.textContent='保存済み';const next=document.getElementById('continueStudy');if(next){next.textContent='別の利用者として学習する';next.href=prefix+'/registration';}}
      else{text.textContent='自動保存した記録に加え、残りの記録と学習の終了を保存します。下のボタンを押してください。';button.disabled=false;}
    }catch(_){storageOk=false;text.textContent='一時記録を読み取れません。実施者に知らせてください。';button.disabled=true;}
  }
  if(finish){
    refresh();
    button.addEventListener('click',async()=>{
      if(finishing)return;
      if(!storageOk){text.textContent='ブラウザ内の記録を確認できません。実施者に知らせてください。';return;}
      finishing=true;button.disabled=true;text.textContent='残りの学習記録を保存しています。この画面を閉じずにお待ちください。';
      try{
        localStorage.setItem(statusKey,'saving');
        if(!localStorage.getItem(root+'finish') && !put('finish',{event_id:participant+':finish',page_id:pageId,client_time:new Date().toISOString(),elapsed_ms:0,event_type:'study_finished',detail:{path:location.pathname}}))throw new Error('storage failed');
        await locked(async()=>{
          // Drain a large offline backlog in bounded batches before completion.
          while(true){
            const batch=batchOf(pending().filter(x=>x.key!==root+'finish'));
            if(!batch.length)break;
            await upload(batch);
          }
          const final=pending().filter(x=>x.key===root+'finish');
          if(final.length)await upload(final,true);
          localStorage.setItem(statusKey,'saved');
        });
        refresh();
      }catch(error){
        text.textContent=error.status===409||error.status===401?'利用者が変わったか、学習の受付が切れています。記録はこのブラウザに残っています。実施者に知らせてください。':'保存できませんでした。記録はこのブラウザに残っています。通信を確認して、もう一度保存してください。';
        button.disabled=false;button.textContent='もう一度保存する';
      }finally{finishing=false;}
    });
    addEventListener('beforeunload',e=>{if(finishing){e.preventDefault();e.returnValue='';}});
    addEventListener('storage',()=>{if(!finishing)refresh();});
    return;
  }
  if(status())notice('この学習は終了しています。続ける場合は「利用者を変更」から名前を入力し直してください。');
  document.addEventListener('click',e=>{clicks++;const el=e.target.closest('a,button,input,summary,[data-key]');event('click',{target:el?(el.id||el.name||el.getAttribute('href')||el.tagName):e.target.tagName});},true);
  document.addEventListener('change',e=>{if(e.target.matches('input[type=radio],input[type=checkbox],select'))event('answer_change',{name:e.target.name,value:e.target.value});});
  function hidden(form,name,value){let input=form.querySelector('input[name="'+name+'"]');if(!input){input=document.createElement('input');input.type='hidden';input.name=name;form.append(input);}input.value=value;}
  function prepareSubmission(form, label){
    if(status()||!storageOk){notice('学習記録を確認してください。新しく始める場合は「利用者を変更」から名前を入力してください。');return false;}
    hidden(form,'_study_participant',participant);hidden(form,'_study_page_id',pageId);hidden(form,'_study_path',location.pathname);hidden(form,'_study_active_ms',Math.round(active()));hidden(form,'_study_elapsed_ms',Math.round(performance.now()-started));hidden(form,'_study_click_count',clicks);hidden(form,'attempt_id',crypto.randomUUID());
    event('submit',{form:label||form.id||form.getAttribute('action')});
    return true;
  }
  window.studyPrepareSubmission=prepareSubmission;
  document.addEventListener('submit',e=>{
    const form=e.target;if(form.method.toLowerCase()!=='post')return;
    if(!prepareSubmission(form)){e.preventDefault();e.stopImmediatePropagation();}
  },true);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){pause();event('page_hidden',{},true);}else{activeSince=performance.now();event('page_visible',{},true);void autosave();}});
  addEventListener('pagehide',()=>{pause();event('page_leave',{},true);});
  addEventListener('pageshow',e=>{if(e.persisted){activeSince=document.hidden?null:performance.now();event('page_visible',{},true);void autosave();}});
  event('page_view');
})();

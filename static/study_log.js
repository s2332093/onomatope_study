(() => {
  const {studyPrefix:prefix, studyParticipant:participant, studyReceipt:receipt, studyFinish:finish} = document.body.dataset;
  if (!prefix || !participant) return;
  const pageId=crypto.randomUUID(), started=performance.now();
  const root='study-log-v3:'+participant+':'+prefix+':', statusKey=root+'status';
  let sequence=0,clicks=0,activeMs=0,activeSince=document.hidden?null:performance.now(),storageOk=true,sending=false;
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
    put(snapshot?'snapshot:'+pageId:'event:'+pageId+':'+sequence++,{event_id:snapshot?pageId+':snapshot':pageId+':'+sequence,page_id:pageId,client_time:new Date().toISOString(),elapsed_ms:Math.round(performance.now()-started),event_type:type,detail:{...detail,path:location.pathname,active_ms:Math.round(active()),click_count:clicks}});
  }
  window.studyEvent=event;
  window.studyRecordReceipt=token=>{if(token)put('receipt:'+crypto.randomUUID(),{receipt:token});};
  if(receipt)window.studyRecordReceipt(receipt);
  // Import unsent events from the previous version without sending them mid-study.
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
      if(key?.startsWith(root) && key!==statusKey){const raw=localStorage.getItem(key);items.push({key,raw,value:JSON.parse(raw)});}
    }
    return items;
  }
  function refresh(){
    if(!finish)return;
    try{
      const items=pending();
      if(status()==='saved' && !items.length){text.textContent='学習記録を保存しました。この画面を閉じてかまいません。';button.disabled=true;button.textContent='保存済み';const next=document.getElementById('continueStudy');if(next){next.textContent='別の利用者として学習する';next.href=prefix+'/registration';}}
      else{text.textContent='学習中の記録はこのブラウザ内にあります。下のボタンを押すと、まとめて保存します。';button.disabled=false;}
    }catch(_){storageOk=false;text.textContent='一時記録を読み取れません。実施者に知らせてください。';button.disabled=true;}
  }
  if(finish){
    refresh();
    button.addEventListener('click',async()=>{
      if(sending)return;
      if(!storageOk){text.textContent='ブラウザ内の記録を確認できません。実施者に知らせてください。';return;}
      sending=true;button.disabled=true;text.textContent='学習記録をまとめて保存しています。この画面を閉じずにお待ちください。';
      try{
        localStorage.setItem(statusKey,'saving');
        if(!put('finish',{event_id:participant+':finish',page_id:pageId,client_time:new Date().toISOString(),elapsed_ms:0,event_type:'study_finished',detail:{path:location.pathname}}))throw new Error('storage failed');
        const batch=pending(), events=batch.filter(x=>!x.value.receipt).map(x=>x.value), receipts=batch.filter(x=>x.value.receipt).map(x=>x.value.receipt);
        const response=await fetch(prefix+'/api/finish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({participant_id:participant,events,receipts})});
        if(!response.ok){const error=new Error('save failed');error.status=response.status;throw error;}
        for(const item of batch)if(localStorage.getItem(item.key)===item.raw)localStorage.removeItem(item.key);
        localStorage.setItem(statusKey,'saved');refresh();
      }catch(error){
        text.textContent=error.status===409||error.status===401?'利用者が変わったか、学習の受付が切れています。記録はこのブラウザに残っています。実施者に知らせてください。':'保存できませんでした。記録はこのブラウザに残っています。通信を確認して、もう一度保存してください。';
        button.disabled=false;button.textContent='もう一度保存する';
      }finally{sending=false;}
    });
    addEventListener('beforeunload',e=>{if(sending){e.preventDefault();e.returnValue='';}});
    addEventListener('storage',()=>{if(!sending)refresh();});
    return;
  }
  if(status())notice('この学習は終了しています。続ける場合は「利用者を変更」から名前を入力し直してください。');
  document.addEventListener('click',e=>{clicks++;const el=e.target.closest('a,button,input,summary,[data-key]');event('click',{target:el?(el.id||el.name||el.getAttribute('href')||el.tagName):e.target.tagName});},true);
  document.addEventListener('change',e=>{if(e.target.matches('input[type=radio],input[type=checkbox],select'))event('answer_change',{name:e.target.name,value:e.target.value});});
  function hidden(form,name,value){let input=form.querySelector('input[name="'+name+'"]');if(!input){input=document.createElement('input');input.type='hidden';input.name=name;form.append(input);}input.value=value;}
  document.addEventListener('submit',e=>{
    const form=e.target;if(form.method.toLowerCase()!=='post')return;
    if(status()||!storageOk){e.preventDefault();e.stopImmediatePropagation();notice('学習記録を確認してください。新しく始める場合は「利用者を変更」から名前を入力してください。');return;}
    hidden(form,'_study_participant',participant);hidden(form,'_study_page_id',pageId);hidden(form,'_study_path',location.pathname);hidden(form,'_study_active_ms',Math.round(active()));hidden(form,'_study_elapsed_ms',Math.round(performance.now()-started));hidden(form,'_study_click_count',clicks);hidden(form,'attempt_id',crypto.randomUUID());
    event('submit',{form:form.id||form.getAttribute('action')});
  },true);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){pause();event('page_hidden',{},true);}else{activeSince=performance.now();event('page_visible',{},true);}});
  addEventListener('pagehide',()=>{pause();event('page_leave',{},true);});
  addEventListener('pageshow',e=>{if(e.persisted){activeSince=document.hidden?null:performance.now();event('page_visible',{},true);}});
  event('page_view');
  setInterval(()=>{if(!document.hidden)event('page_snapshot',{},true);},5000);
})();

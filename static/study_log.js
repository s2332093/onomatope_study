(() => {
  const prefix = document.body.dataset.studyPrefix;
  const participant = document.body.dataset.studyParticipant;
  if (!prefix || !participant) return;
  const pageId = crypto.randomUUID(), started = performance.now();
  const storageKey = 'study-events-v2:' + participant + ':' + prefix;
  let sequence = 0, clicks = 0, activeMs = 0;
  let activeSince = document.hidden ? null : performance.now();
  let sending = false, queue = [];
  try { queue = JSON.parse(sessionStorage.getItem(storageKey) || '[]'); } catch (_) {}
  function persist() {
    try { sessionStorage.setItem(storageKey, JSON.stringify(queue)); } catch (_) {}
  }
  function active() {
    return activeMs + (activeSince === null ? 0 : performance.now() - activeSince);
  }
  function notice(failed) {
    let el = document.getElementById('studySaveStatus');
    if (!el && failed) {
      el = document.createElement('p'); el.id = 'studySaveStatus';
      el.setAttribute('role','status');
      el.style.cssText = 'position:fixed;bottom:8px;right:12px;z-index:1000;background:#fff4df;border:1px solid #e8890c;padding:10px;border-radius:8px;font-size:13px;max-width:300px';
      document.body.append(el);
    }
    if (el) { el.hidden = !failed; el.textContent = '記録を保存できていません。通信を確認してください。自動で再送します。'; }
  }
  async function flush() {
    if (sending || !queue.length) return;
    sending = true;
    const batch = queue.slice(0,100);
    try {
      const response = await fetch(prefix + '/api/events', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({events:batch}), keepalive:true
      });
      if (!response.ok) throw new Error('save failed');
      const saved = new Set(batch.map(e=>e.event_id));
      queue = queue.filter(e=>!saved.has(e.event_id));
      persist(); notice(false);
    } catch (_) { notice(true); }
    finally { sending = false; }
  }
  function beacon() {
    if (!queue.length) return;
    // Keep unacknowledged events for retry; the server ignores duplicate IDs.
    if (navigator.sendBeacon) navigator.sendBeacon(prefix + '/api/events', new Blob([JSON.stringify({events:queue.slice(0,100)})],{type:'application/json'}));
  }
  window.studyEvent = (type, detail = {}) => {
    queue.push({event_id:pageId+':'+sequence++,page_id:pageId,
      client_time:new Date().toISOString(),elapsed_ms:Math.round(performance.now()-started),
      event_type:type,detail:{...detail,path:location.pathname,active_ms:Math.round(active()),click_count:clicks}});
    persist();
    if (queue.length>=20) flush();
  };
  document.addEventListener('click', e => {
    clicks++;
    const el = e.target.closest('a,button,input,summary,[data-key]');
    window.studyEvent('click',{target:el ? (el.id || el.name || el.getAttribute('href') || el.tagName) : e.target.tagName});
  },true);
  document.addEventListener('change', e => {
    if (e.target.matches('input[type=radio],input[type=checkbox],select'))
      window.studyEvent('answer_change',{name:e.target.name,value:e.target.value});
  });
  function hidden(form,name,value) {
    let input = form.querySelector('input[name="'+name+'"]');
    if (!input) { input=document.createElement('input');input.type='hidden';input.name=name;form.append(input); }
    input.value=value;
  }
  document.addEventListener('submit', e => {
    // Capture before the matching screen intercepts submit for inline feedback.
    const form=e.target;
    if (form.method.toLowerCase()!=='post') return;
    hidden(form,'_study_page_id',pageId);
    hidden(form,'_study_path',location.pathname);
    hidden(form,'_study_active_ms',Math.round(active()));
    hidden(form,'_study_elapsed_ms',Math.round(performance.now()-started));
    hidden(form,'_study_click_count',clicks);
    hidden(form,'attempt_id',crypto.randomUUID());
    window.studyEvent('submit',{form:form.id || form.getAttribute('action')});
    flush();
  },true);
  document.addEventListener('visibilitychange',()=>{
    if (document.hidden) {
      if(activeSince!==null) activeMs+=performance.now()-activeSince;
      activeSince=null;window.studyEvent('page_hidden');beacon();
    } else {
      activeSince=performance.now();window.studyEvent('page_visible');flush();
    }
  });
  addEventListener('pagehide',()=>{window.studyEvent('page_leave');beacon();});
  addEventListener('pageshow',e=>{if(e.persisted){activeSince=document.hidden?null:performance.now();window.studyEvent('page_visible');flush();}});
  addEventListener('online',flush);
  window.studyEvent('page_view');flush();
  setInterval(()=>{if(!document.hidden) window.studyEvent('heartbeat');flush();},5000);
})();
